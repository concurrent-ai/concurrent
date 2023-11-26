from dataclasses import dataclass
import io
import json
import os
import logging
from typing import List, Tuple
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(process)d - %(name)s - %(levelname)s - %(message)s")

import traceback
import boto3
import tempfile
import uuid
import time
import base64
import zlib
from google.cloud import container_v1
import google.auth
import google.auth.transport.requests
from kubernetes import client as kubernetes_client
from tempfile import NamedTemporaryFile, mkstemp

from utils import get_service_conf, get_subscriber_info, get_cognito_user, get_custom_token
from kube_clusters import query_user_accessible_clusters
from kubernetes import config
from kubernetes.client import models as k8s
from kubernetes.client import api_client, Configuration
from kubernetes.client.rest import ApiException
import kubernetes.utils
import yaml

import utils
# pylint: disable=logging-not-lazy,bad-indentation,broad-except,logging-fstring-interpolation

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def respond(err, res=None) -> dict:
    return {
        'statusCode': '400' if err else '200',
        'body': str(err) if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*',
            'Access-Control-Allow-Credentials': '*'
        },
    }

def deploy_model(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)
    success, status, subs = get_subscriber_info(cognito_username) 
    if not success: return respond(ValueError(status))
    
    success, status, service_conf = get_service_conf()
    if not success: return respond(ValueError(status))
    
    body = event['body']
    # example: '{"backend-type": "gke", "kube-context": "isstage23-cluster-1", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}'
    item = json.loads(body)

    #Inject Parallels token in the body
    token_info = get_custom_token(cognito_username, groups)
    item['parallels_token']="Custom {0}:{1}".format(token_info['queue_message_uuid'], token_info['token'])

    logger.info('msg payload item=' + str(item))

    backend_type = item.get('backend_type')

    if backend_type == 'eks':
        return deploy_model_eks(cognito_username, groups, context, subs, item, service_conf)
    if backend_type == 'gke':
        return deploy_model_gke(cognito_username, groups, context, subs, item, service_conf)
    elif backend_type == HpeClusterConfig.HPE_CLUSTER_TYPE:
        return _deploy_model_hpe(cognito_username, groups, context, subs, item, service_conf)
    else:
        err = 'deploy_model: Error. Unknown backend type ' + backend_type
        logger.error(err)
        return respond(ValueError(err))


def lookup_gke_cluster_config(cognito_username, groups, kube_cluster_name, subs):
    # First lookup user specific cluster
    gke_location_type, gke_location, gke_project_id, gke_creds = None, None, None, None
    kube_clusters = query_user_accessible_clusters(cognito_username, groups)
    for cl in kube_clusters:
        if cl['cluster_name'] == kube_cluster_name and cl['cluster_type'] == 'GKE':
            logger.info("Found user's cluser " + kube_cluster_name)
            return cl['gke_location_type'], cl['gke_location'], cl['gke_project'], cl['gke_creds']

    logger.info("Use cluster info for subscriber")
    # Fall back to subscriber's cluster
    gke_location = subs['gke_location']['S']
    gke_location_type = subs['gke_location_type']['S']
    gke_project_id = subs['gke_project']['S']
    gke_creds = subs['gke_creds']['S']

    return gke_location_type, gke_location, gke_project_id, gke_creds


def deploy_model_gke(cognito_username, groups, context, subs, item, service_conf:dict): # pylint: disable=unused-argument
    logger.info("deploy_model_gke: Running in kube. item=" + str(item) + ', service_conf=' + str(service_conf))
    if not 'kube_context' in item:
        return respond(ValueError('Project Backend Configuration must include kube_context'))

    gke_cluster_name = item['kube_context']
    gke_location_type, gke_location, gke_project_id, gke_creds \
        = lookup_gke_cluster_config(cognito_username, groups, gke_cluster_name, subs)

    _, creds_file_path = mkstemp(suffix='.json', text=True)
    with open(creds_file_path, 'w') as tmp_creds_file:
        print('{}'.format(gke_creds), file=tmp_creds_file)
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_file_path
    creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)

    container_client = container_v1.ClusterManagerClient()
    if gke_location_type.lower() == 'regional':
      name= 'projects/' + gke_project_id + '/region/' + gke_location + '/clusters/' + gke_cluster_name
    elif gke_location_type.lower() == 'zonal':
      name= 'projects/' + gke_project_id + '/zone/' + gke_location + '/clusters/' + gke_cluster_name
    response = container_client.get_cluster(name=name)
    logger.info('Cluster=' + str(response))

    configuration = kubernetes_client.Configuration()
    configuration.host = f'https://{response.endpoint}'
    with NamedTemporaryFile(delete=False) as ca_cert:
      ca_cert.write(base64.b64decode(response.master_auth.cluster_ca_certificate))
    configuration.ssl_ca_cert = ca_cert.name
    configuration.api_key_prefix['authorization'] = 'Bearer'
    configuration.api_key['authorization'] = creds.token
    # if GKE cluster is in 'RECONCILING' state, api server may not be reachable.  Wait for the api server to recover for 10 minutes.  Note that execute_dag(), which calls deploy_model(), will not retry this call again
    # https://github.com/kubernetes-client/python/pull/780; https://github.com/swagger-api/swagger-codegen/pull/9284/files
    api_server_retries:int=int(service_conf['K8sApiServerRetries']['N']) if service_conf.get('K8sApiServerRetries') else 10  # prev default of 5 was giving us only 4 mins
    configuration.retries = api_server_retries

    # cfg = kubernetes_client.ApiClient(configuration)
    # k8s_client = kubernetes_client.BatchV1Api(cfg)        
    # # comment since it can overload the api server if there are 1000s of jobs.  
    # # Raises ApiException if can't connect and times out??
    # ret:kubernetes_client.V1JobList = k8s_client.list_job_for_all_namespaces()
    # logger.info(utils.filter_empty_in_dict_list_scalar(ret.to_dict()))

    _kickoff_bootstrap('gke', response.endpoint, response.master_auth.cluster_ca_certificate, None,
                    item, None, None, None, None, None, None, None, None, None,
                    gke_project_id, gke_creds, empty_hpe_cluster_config, cognito_username, subs, configuration)
    os.remove(creds_file_path)
    return respond(None, {})

def _create_prio_class(con, name, val, global_default, preemption_policy=None):
    api_resp = None
    api_instance = kubernetes_client.SchedulingV1Api(api_client=api_client.ApiClient(configuration=con))
    try:
        api_resp:kubernetes_client.V1PriorityClass = api_instance.read_priority_class(name)
    except ApiException as ae:
        print('While reading ' + str(name) + ', caught ' + str(ae))
        _do_create_prio_class(con, name, val, global_default, preemption_policy=preemption_policy)
    else:
        print(f'Successfully read priority class name={name} api_resp={ yaml.safe_dump(utils.filter_empty_in_dict_list_scalar(api_resp.to_dict()))}')
        return

def _do_create_prio_class(con, name, val, global_default, preemption_policy=None):
    api_resp = None
    api_instance = kubernetes_client.SchedulingV1Api(api_client=api_client.ApiClient(configuration=con))
    body = kubernetes_client.V1PriorityClass(value=val, metadata=kubernetes_client.V1ObjectMeta(name=name),
                                             global_default=global_default, preemption_policy=preemption_policy)
    try:
        api_resp:kubernetes_client.V1PriorityClass = api_instance.create_priority_class(body)
    except ApiException as ae:
        print('While creating ' + str(name) + ', caught ' + str(ae))
    else:
        print(f'Successfully created priority class name = {name}; api_resp = { yaml.safe_dump(utils.filter_empty_in_dict_list_scalar(api_resp.to_dict())) }')

def _create_prio_classes(con):
    _create_prio_class(con, 'concurrent-high-non-preempt-prio', 1000, False, preemption_policy='Never')
    _create_prio_class(con, 'parallels-lo-prio', 100, True)

@dataclass
class HpeClusterConfig:
    HPE_CLUSTER_TYPE = 'HPE'
    
    # .kube/config file for access to the cluster.  This is for access from the internet
    hpeKubeConfig: str
    # .kube/config file for access to the cluster.  This is for access from the Private network (non internet)
    hpeKubeConfigPrivateNet: str
    # the context name in kube_config
    hpeKubeConfigContext:str
    # uri of container registry: like registry-service:5000 or public.ecr.aws/y9l4v0u6/
    hpeContainerRegistryUri: str    
empty_hpe_cluster_config = HpeClusterConfig("", "", "", "")    

def _kickoff_bootstrap(backend_type, endpoint, cert_auth, cluster_arn, item,
                        eks_access_key_id, eks_secret_access_key, eks_session_token, ecr_type, ecr_region,
                        ecr_access_key_id, ecr_secret_access_key, ecr_session_token, ecr_aws_account_id,
                        gke_project_id, gke_creds, hpe_cluster_config:HpeClusterConfig, cognito_username:str, subs:dict, con:Configuration):
    """
    _summary_

    _extended_summary_

    Args:
        backend_type (_type_): _description_
        endpoint (_type_): _description_
        cert_auth (_type_): _description_
        cluster_arn (_type_): _description_
        item (_type_): This is the POST data for runProject along with other added keys.  example: {"backend-type": "HPE", "kube-context": "isstage23-cluster-1", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}
        eks_access_key_id (_type_): _description_
        eks_secret_access_key (_type_): _description_
        eks_session_token (_type_): _description_
        ecr_type (_type_): _description_
        ecr_region (_type_): _description_
        ecr_access_key_id (_type_): _description_
        ecr_secret_access_key (_type_): _description_
        ecr_session_token (_type_): _description_
        ecr_aws_account_id (_type_): _description_
        gke_project_id (_type_): _description_
        gke_creds (_type_): _description_
        hpe_cluster_config (HpeClusterConfig): _description_
        cognito_username (str): _description_
        subs (dict): subscriber information
        con (Configuration): _description_
    """
    _create_prio_classes(con)
    run_id = item['run_id']
    canonical_nm = 'mlflow-deploy-bootstrap-' + run_id
    if 'namespace' in item:
        namespace = item['namespace']
    else:
        namespace = 'default'
    print('run_mlflow_project_kube: namespace=' + str(namespace))

    cmap = kubernetes_client.V1ConfigMap()
    cmap.metadata = kubernetes_client.V1ObjectMeta(name=canonical_nm)
    cmap.data = {}
    cmap.data['BACKEND_TYPE'] = backend_type
    cmap.data['ENDPOINT'] = endpoint
    cmap.data['CERT_AUTH'] = cert_auth
    if cluster_arn:
        cmap.data['CLUSTER_ARN'] = cluster_arn
    cmap.data['MLFLOW_CONCURRENT_URI'] = item['MLFLOW_CONCURRENT_URI']
    cmap.data['MLFLOW_TRACKING_URI'] = item['MLFLOW_TRACKING_URI']
    cmap.data['MLFLOW_RUN_ID'] = run_id
    cmap.data['NAMESPACE'] = namespace
    if backend_type == 'eks':
        cmap.data['ECR_TYPE'] = ecr_type
        cmap.data['ECR_REGION'] = ecr_region
    elif backend_type == 'gke':
        cmap.data['PROJECT_ID'] = gke_project_id
    elif backend_type == HpeClusterConfig.HPE_CLUSTER_TYPE:
        cmap.data['HPE_CONTAINER_REGISTRY_URI'] = hpe_cluster_config.hpeContainerRegistryUri
    if ecr_aws_account_id:
        cmap.data['ECR_AWS_ACCOUNT_ID'] = ecr_aws_account_id

    if 'docker_image' in item:
        cmap.data['DOCKER_IMAGE'] = item['docker_image']
    else:
        cmap.data['DOCKER_IMAGE'] = 'mlflow-docker-example'

    cmap.data['MLFLOW_EXPERIMENT_ID'] = item['experiment_id']
    if 'docker_repo_name' in item:
        cmap.data['DOCKER_REPO_NAME'] = item['docker_repo_name']
    cmap.data['COGNITO_USERNAME'] = cognito_username
    if "resources.limits.cpu" in item:
        cmap.data['RESOURCES_LIMITS_CPU'] = item['resources.limits.cpu']
    if "resources.limits.memory" in item:
        cmap.data['RESOURCES_LIMITS_MEMORY'] = item['resources.limits.memory']
    if "resources.limits.hugepages" in item:
        cmap.data['RESOURCES_LIMITS_HUGEPAGES'] = item['resources.limits.hugepages']
    if "resources.limits.nvidia.com/gpu" in item:
        cmap.data['RESOURCES_LIMITS_NVIDIA_COM_GPU'] = item['resources.limits.nvidia.com/gpu']
    if "resources.requests.cpu" in item:
        cmap.data['RESOURCES_REQUESTS_CPU'] = item['resources.requests.cpu']
    if "resources.requests.memory" in item:
        cmap.data['RESOURCES_REQUESTS_MEMORY'] = item['resources.requests.memory']
    if "resources.requests.hugepages" in item:
        cmap.data['RESOURCES_REQUESTS_HUGEPAGES'] = item['resources.requests.hugepages']
    if "optimizer-technology" in item:
        cmap.data['OPTIMIZER_TECHNOLOGY'] = item['optimizer-technology']
    else:
        cmap.data['OPTIMIZER_TECHNOLOGY'] = 'no-optimizer'
    if "resources.requests.nvidia.com/gpu" in item:
        gpu_count = item['resources.requests.nvidia.com/gpu']
        if int(gpu_count) > 0:
            cmap.data['RESOURCES_REQUESTS_NVIDIA_COM_GPU'] = gpu_count
    elif 'resources.requests.gpu' in item:
        gpu_count = item['resources.requests.gpu']
        if int(gpu_count) > 0:
            cmap.data['RESOURCES_REQUESTS_NVIDIA_COM_GPU'] = gpu_count
    if 'params' in item:
        print('params=' + str(item['params']))
        cmap.data['PROJECT_PARAMS'] = base64.b64encode(json.dumps(item['params']).encode('utf-8'), altchars=None).decode('utf-8')
    else:
        print('No params')
    if 'kube_job_template_contents' in item:
        cmap.data['KUBE_JOB_TEMPLATE_CONTENTS'] = item['kube_job_template_contents']
    if 'additionalPackages' in subs:
        cmap.data['ADDITIONAL_PACKAGES'] = subs['additionalPackages']['S']
    if 'additionalImports' in subs:
        cmap.data['ADDITIONAL_IMPORTS'] = subs['additionalImports']['S']
    cmap.data['MODEL_URI'] = item['model_uri']

    # this is the command that'll be used to install concurrent in the bootstrap and the mlflow project pod.  Set this in subscribers table to something similar to "pip install --no-cache-dir --upgrade http://xyz.com/packages/concurrent-plugin/concurrent_plugin-0.3.27-py3-none-any.whl"
    if 'concurrentPluginPipInstallCmd' in subs: cmap.data['CONCURRENT_PLUGIN_PIP_INSTALL_CMD'] = subs['concurrentPluginPipInstallCmd']['S']
    if 'concurrentPrivilegedMlflowContainer' in subs: cmap.data['CONCURRENT_PRIVILEGED_MLFLOW_CONTAINER'] = subs['concurrentPrivilegedMlflowContainer']['S']
    # PYTHONUNBUFFERED is an environment variable in Python that can be used to disable output buffering for all streams. When this variable is set to a non-empty string, Python automatically sets the PYTHONUNBUFFERED flag, which forces Python to disable buffering for sys.stdout and sys.stderr.
    cmap.data['PYTHONUNBUFFERED'] = 'true'
        
    tokfile_contents = 'Token=' + item['parallels_token'] + '\n'
    if backend_type == 'eks':
        credsfile_contents = '[default]\naws_access_key_id=' + eks_access_key_id + '\n' + 'aws_secret_access_key=' + eks_secret_access_key + '\n'
        if eks_session_token:
            credsfile_contents = credsfile_contents + 'aws_session_token=' + eks_session_token + '\n\n'
        if ecr_access_key_id and ecr_secret_access_key:
            credsfile_contents = credsfile_contents + '[ecr]\naws_access_key_id=' + ecr_access_key_id + '\n' + 'aws_secret_access_key=' + ecr_secret_access_key + '\n'
        if ecr_session_token:
            credsfile_contents = credsfile_contents + 'aws_session_token=' + ecr_session_token + '\n'
        gce_keyfile_contents = 'GCE Keyfile unused for eks'
    elif backend_type == 'gke':
        credsfile_contents = '# AWS Credentials file unused for ' + backend_type
        gce_keyfile_contents = gke_creds
    elif backend_type == HpeClusterConfig.HPE_CLUSTER_TYPE:
        credsfile_contents = '# AWS Credentials file unused for ' + backend_type
        gce_keyfile_contents = 'GCE Keyfile unused for ' + backend_type
        
    core_v1_api:kubernetes_client.CoreV1Api = kubernetes_client.CoreV1Api(api_client=api_client.ApiClient(configuration=con))
    batch_v1_api:kubernetes_client.BatchV1Api = kubernetes_client.BatchV1Api(api_client=api_client.ApiClient(configuration=con))
    volume_mounts, volumes = setup_secrets(cognito_username, backend_type, core_v1_api, namespace, tokfile_contents, credsfile_contents,
                                           gce_keyfile_contents, hpe_cluster_config, subs, cmap)

    core_v1_api.create_namespaced_config_map(namespace=namespace, body=cmap)

    if 'deployModelImage' in subs:
        bootstrap_image = subs['deployModelImage']['S']
        logger.info(f'kickoff_bootstrap: using subs table override bootstrap_image {bootstrap_image}')
    else:
        bootstrap_image = 'public.ecr.aws/u5q3r5r0/deploy-model'
        logger.info(f'kickoff_bootstrap: using default bootstrap_image {bootstrap_image}')

    try:
        pod_failure_policy = kubernetes_client.V1PodFailurePolicy([
            kubernetes_client.V1PodFailurePolicyRule(action="Ignore", on_exit_codes=kubernetes_client.V1PodFailurePolicyOnExitCodesRequirement(operator="In", values=[143])),
            kubernetes_client.V1PodFailurePolicyRule(action="FailJob", on_exit_codes=kubernetes_client.V1PodFailurePolicyOnExitCodesRequirement(operator="NotIn", values=[0])),
            kubernetes_client.V1PodFailurePolicyRule(action="Ignore", on_pod_conditions=[kubernetes_client.V1PodFailurePolicyOnPodConditionsPattern(status="True", type="DisruptionTarget")])
            ])
        pod_template = kubernetes_client.V1PodTemplateSpec(
            metadata=kubernetes_client.V1ObjectMeta(name=canonical_nm, labels={"pod_name": canonical_nm}, namespace=namespace),
            spec=kubernetes_client.V1PodSpec(
                containers=[
                    kubernetes_client.V1Container(
                        name=canonical_nm,
                        image = bootstrap_image,
                        env_from=[
                            kubernetes_client.V1EnvFromSource(
                                config_map_ref=kubernetes_client.V1ConfigMapEnvSource(name=canonical_nm)
                            )
                        ],
                        env=[
                            kubernetes_client.V1EnvVar(name='MY_POD_NAME', 
                                value_from=kubernetes_client.V1EnvVarSource(
                                    field_ref=kubernetes_client.V1ObjectFieldSelector(
                                        field_path='metadata.name'
                                    )
                                )
                            )
                        ],
                        security_context=kubernetes_client.V1SecurityContext(privileged=True),
                        volume_mounts=volume_mounts,
                        resources = kubernetes_client.V1ResourceRequirements(requests={'cpu': '1250m', 'memory': '7168M'}, limits={'cpu': '1250m', 'memory': '7168M'})
                    )
                ],
                restart_policy='Never',
                priority_class_name='parallels-lo-prio',
                volumes=volumes,
                # service_account_name='infinstor-serviceaccount-' + namespace
                service_account_name='k8s-serviceaccount-for-parallels-' + namespace,
                tolerations=[kubernetes_client.V1Toleration(key="concurrent-node-type", operator="Equal", value="system", effect="NoSchedule")]
                )
            )
        job = kubernetes_client.V1Job(
                api_version="batch/v1",
                kind="Job",
                metadata=kubernetes_client.V1ObjectMeta(name=canonical_nm, namespace=namespace, labels={"job_name": canonical_nm}),
                spec=kubernetes_client.V1JobSpec(ttl_seconds_after_finished=60, completions=1, template=pod_template, pod_failure_policy=pod_failure_policy)
            )
        logger.info(f'kickoff_bootstrap: creating namespaced job={job}')
    except Exception as exp1:
        traceback.print_exc()
        logger.info(f'kickoff_bootstrap: Caught {exp1}')
        return

    try:
        arv = batch_v1_api.create_namespaced_job(namespace=namespace,body=job)
    except Exception as ex:
        traceback.print_exc()
        logger.error('kickoff_bootstrap: create_namespaced_pod of bootstrap caught ' + str(ex))
    else:
        logger.info(f'kickoff_bootstrap: create_namespaced_pod of bootstrap returned api_ver={ yaml.safe_dump(utils.filter_empty_in_dict_list_scalar(arv.to_dict())) }')

def lookup_eks_cluster_config(cognito_username, groups, kube_cluster_name, subs):
    # First lookup user specific cluster
    eks_region, eks_role, eks_role_ext = None, None, None
    kube_clusters = query_user_accessible_clusters(cognito_username, groups)
    for cl in kube_clusters:
        if cl['cluster_name'] == kube_cluster_name and cl['cluster_type'] == 'EKS':
            logger.info("Found user's cluser " + kube_cluster_name)
            return cl['eks_region'], cl['eks_role'], cl['eks_role_ext'], cl['ecr_role'], \
                    cl['ecr_role_ext'], cl['ecr_type'], cl['ecr_region']

    logger.info("Use cluster info for subscriber")
    # Fall back to subscriber's cluster
    if 'eksRegion' in subs:
        eks_region = subs['eksRegion']['S']
    else:
        eks_region = 'us-east-1'
    if 'eksRole' in subs:
        eks_role = subs['eksRole']['S']
    if 'eksRoleExt' in subs:
        eks_role_ext = subs['eksRoleExt']['S']
    if 'ecrRegion' in subs:
        ecr_region = subs['ecrRegion']['S']
    else:
        ecr_region = 'us-east-1'
    if 'ecrType' in subs:
        ecr_type = subs['ecrType']['S']
    if 'ecrRole' in subs:
        ecr_role = subs['ecrRole']['S']
    if 'ecrRoleExt' in subs:
        ecr_role_ext = subs['ecrRoleExt']['S']

    return eks_region, eks_role, eks_role_ext, ecr_role, ecr_role_ext, ecr_type, ecr_region

def _lookup_hpe_cluster_config(cognito_username:str, groups:list, kube_cluster_name: str, subs:dict) -> HpeClusterConfig:
    # first try user's kube clusters
    kube_clusters:list = query_user_accessible_clusters(cognito_username, groups)
    for user_clust in kube_clusters:
        if user_clust['cluster_type'] == HpeClusterConfig.HPE_CLUSTER_TYPE and user_clust['cluster_name'] == kube_cluster_name :
            return HpeClusterConfig(user_clust['hpeKubeConfig'], user_clust['hpeKubeConfigPrivateNet'], user_clust['hpeKubeConfigContext'], user_clust['hpeContainerRegistryUri'])
    
    # fall back to subscriber's cluster information
    logger.info("Use cluster info for subscriber")
    return HpeClusterConfig(
        subs['hpeKubeConfig']['S'] if 'hpeKubeConfig' in subs else None,
        subs['hpeKubeConfigPrivateNet']['S'] if 'hpeKubeConfigPrivateNet' in subs else None,
        subs['hpeKubeConfigContext']['S'] if 'hpeKubeConfigContext' in subs else None,
        subs['hpeContainerRegistryUri']['S'] if 'hpeContainerRegistryUri' in subs else None
    )

def _deploy_model_hpe(cognito_username:str, groups, context, subs:dict, reqbody:dict, service_conf:dict):  #pylint: disable=unused-argument
    """
    _summary_

    _extended_summary_

    Args:
        cognito_username (str): _description_
        context (_type_): _description_
        subs (dict): _description_
        reqbody (dict): example: {"backend-type": "HPE", "kube-context": "isstage23-cluster-1", "kube-namespace": "parallelsns", "resources.requests.memory": "1024Mi", "kube-client-location": "backend"}
        service_conf (dict): _description_
    """
    hpe_cluster_conf:HpeClusterConfig = _lookup_hpe_cluster_config(cognito_username, groups, reqbody['kube_context'], subs)
    print(f"hpe_cluster_conf={hpe_cluster_conf}")
    
    # write kube config to temp file
    kube_config_fname = os.path.join(tempfile.mkdtemp(),'config')
    with open(kube_config_fname, 'w') as f:
        f.write(hpe_cluster_conf.hpeKubeConfig)
        
    # create a kube config from its string representation
    kube_config:Configuration = Configuration()
    # api server may not be reachable.  Wait for the api server to recover for 10 minutes.  Note that execute_dag(), which calls deploy_model(), will not retry this call again
    # https://github.com/kubernetes-client/python/pull/780; https://github.com/swagger-api/swagger-codegen/pull/9284/files
    api_server_retries:int=int(service_conf['K8sApiServerRetries']['N']) if service_conf.get('K8sApiServerRetries') else 10  # prev default of 5 was giving us only 4 mins
    kube_config.retries = api_server_retries
    # Loads authentication and cluster information from kube-config file and stores them in kubernetes.client.configuration.
    # config_file: Name of the kube-config file.
    # client_configuration: The kubernetes.client.Configuration to set configs to.
    config.load_kube_config(config_file=kube_config_fname, client_configuration=kube_config)
    
    _kickoff_bootstrap(HpeClusterConfig.HPE_CLUSTER_TYPE, endpoint=None, cert_auth=None, cluster_arn=None, item=reqbody, eks_access_key_id=None, eks_secret_access_key=None, eks_session_token=None, ecr_type=None, ecr_region=None, ecr_access_key_id=None, ecr_secret_access_key=None, ecr_session_token=None, ecr_aws_account_id=None, gke_project_id=None, gke_creds=None, hpe_cluster_config=hpe_cluster_conf, cognito_username=cognito_username, subs=subs, con=kube_config)
    
    return respond(None, {})

def deploy_model_eks(cognito_username, groups, context, subs, item, service_conf):   # pylint: disable=unused-argument
    logger.info("deploy_model: Running in kube. item=" + str(item) + ', service_conf=' + str(service_conf))
    if not 'kube_context' in item:
        return respond(ValueError('Project Backend Configuration must include kube_context'))
    kube_cluster_name = item['kube_context']

    eks_access_key_id = None
    eks_secret_access_key = None
    eks_session_token = None

    eks_region, eks_role, eks_role_ext, \
        ecr_role, ecr_role_ext, ecr_type, ecr_region \
        = lookup_eks_cluster_config(cognito_username, groups, kube_cluster_name, subs)
    ecr_aws_account_id = None

    if eks_role and eks_role_ext:
        sts_client = boto3.client('sts')
        assumed_role_object = sts_client.assume_role(
                RoleArn=eks_role,
                ExternalId=eks_role_ext,
                RoleSessionName=str(uuid.uuid4()))
        eks_access_key_id = assumed_role_object['Credentials']['AccessKeyId']
        eks_secret_access_key = assumed_role_object['Credentials']['SecretAccessKey']
        eks_session_token = assumed_role_object['Credentials']['SessionToken']

    if eks_session_token:
        eks_client = boto3.client('eks', aws_access_key_id=eks_access_key_id,
                aws_secret_access_key=eks_secret_access_key, aws_session_token=eks_session_token,
                region_name=eks_region)
    else:
        eks_client = boto3.client('eks', aws_access_key_id=eks_access_key_id,
                aws_secret_access_key=eks_secret_access_key, region_name=eks_region)
    resp = eks_client.describe_cluster(name=kube_cluster_name)

    print('run_mlflow_project_kube: describe_cluster res=' + str(resp))
    endpoint = resp['cluster']['endpoint']
    print('run_mlflow_project_kube: endpoint=' + str(endpoint))
    cert_auth = resp['cluster']['certificateAuthority']['data']
    print('run_mlflow_project_kube: cert_auth=' + str(cert_auth))
    cluster_arn = resp['cluster']['arn']
    print('run_mlflow_project_kube: cluster_arn=' + str(cluster_arn))

    # write kube config file
    cdir = tempfile.mkdtemp()
    with open(os.path.join(cdir, 'config'), "w") as fh:
        fh.write('apiVersion: v1\n')
        fh.write('clusters:\n')
        fh.write('- cluster:\n')
        fh.write('    certificate-authority-data: ' + cert_auth + '\n')
        fh.write('    server: ' + endpoint + '\n')
        fh.write('  name: ' + cluster_arn + '\n')
        fh.write('contexts:\n')
        fh.write('- context:\n')
        fh.write('    cluster: ' + cluster_arn + '\n')
        fh.write('    user: ' + cluster_arn + '\n')
        fh.write('  name: ' + cluster_arn + '\n')
        fh.write('current-context: ' + cluster_arn + '\n')
        fh.write('kind: Config\n')
        fh.write('preferences: {}\n')
        fh.write('users:\n')
        fh.write('- name: ' + cluster_arn + '\n')
        fh.write('  user:\n')
        #fh.write('    token:' + token + '\n')
        fh.write('    exec:\n')
        fh.write('      apiVersion: client.authentication.k8s.io/v1alpha1\n')
        fh.write('      command: python\n')
        fh.write('      args:\n')
        fh.write('        - ' + os.path.join(os.getcwd(), 'eks_get_token.py') + '\n')
        fh.write('      env:\n')
        fh.write('        - name: "AWS_ACCESS_KEY_ID"\n')
        fh.write('          value: "' + eks_access_key_id + '"\n')
        fh.write('        - name: "AWS_SECRET_ACCESS_KEY"\n')
        fh.write('          value: "' + eks_secret_access_key + '"\n')
        if eks_session_token:
            fh.write('        - name: "AWS_SESSION_TOKEN"\n')
            fh.write('          value: "' + eks_session_token + '"\n')
        fh.write('        - name: "EKS_CLUSTER_NAME"\n')
        fh.write('          value: "' + kube_cluster_name + '"\n')
    logger.debug(open(os.path.join(cdir, 'config')).read())
    con:Configuration = type.__call__(Configuration)
    # api server may not be reachable.  Wait for the api server to recover for 10 minutes.  Note that execute_dag(), which calls deploy_model(), will not retry this call again
    # https://github.com/kubernetes-client/python/pull/780; https://github.com/swagger-api/swagger-codegen/pull/9284/files
    api_server_retries:int=int(service_conf['K8sApiServerRetries']['N']) if service_conf.get('K8sApiServerRetries') else 10  # prev default of 5 was giving us only 4 mins
    con.retries = api_server_retries
    # con.debug = True
    config.load_kube_config(config_file=os.path.join(cdir, 'config'), client_configuration=con)
    # hand off job to kube. First, delete existing ConfigMap, create new ConfigMap
    if ecr_role and ecr_role_ext and ecr_type and ecr_region:
        ecr_assumed_role_object = sts_client.assume_role(
                RoleArn=ecr_role,
                ExternalId=ecr_role_ext,
                RoleSessionName=str(uuid.uuid4()))
        ecr_access_key_id=ecr_assumed_role_object['Credentials']['AccessKeyId']
        ecr_secret_access_key=ecr_assumed_role_object['Credentials']['SecretAccessKey']
        ecr_session_token=ecr_assumed_role_object['Credentials']['SessionToken']
        if ecr_type == 'private':
            ss = ecr_role.split(':')
            ecr_aws_account_id=ss[4]
    else:
        err = 'deploy_model_eks: ecr role, ext, region and type must be specified'
        logger.error(err)
        return respond(ValueError(err))

    _kickoff_bootstrap('eks', endpoint, cert_auth, cluster_arn, item, eks_access_key_id, eks_secret_access_key, eks_session_token,
                        ecr_type, ecr_region, ecr_access_key_id, ecr_secret_access_key, ecr_session_token, ecr_aws_account_id,
                        None, None, empty_hpe_cluster_config, cognito_username, subs, con)
    return respond(None, {})

    
def setup_secrets(cognito_username:str, backend_type:str, core_api_instance:kubernetes_client.CoreV1Api, job_namespace, tokfile_contents, credsfile_contents,
                  gce_keyfile_contents, hpe_cluster_config:HpeClusterConfig, subs:dict, cmap:kubernetes_client.V1ConfigMap) -> Tuple[List[kubernetes_client.V1VolumeMount], List[kubernetes_client.V1Volume]]:   # pylint: disable=unused-argument
    """
    _summary_

    _extended_summary_

    Args:
        cognito_username (str): cognito user name
        backend_type (str): _description_
        core_api_instance (kubernetes_client.CoreV1Api): _description_
        job_namespace (_type_): _description_
        tokfile_contents (_type_): _description_
        credsfile_contents (_type_): _description_
        gce_keyfile_contents (_type_): _description_
        hpe_cluster_config (HpeClusterConfig): cannot be None.  Can be an empty instance
        subs (dict): subscriber information
        cmap (kubernetes.client.V1ConfigMap): the config map to add entries into, if needed
        
    Returns:
        Tuple[List[kubernetes_client.V1VolumeMount], List[kubernetes_client.V1Volume]]: returns the tuple (list_of_volume_mounts, list_of_volumes) on success; on error, returns (None, None)
    
    Raises:
        An exception on failure
    """
    tok = base64.b64encode(tokfile_contents.encode('utf-8')).decode('utf-8')
    unique_suffix = str(uuid.uuid4())
    token_secret_name = 'parallelstokenfile-' + unique_suffix
    try:
        core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=token_secret_name)
    except Exception:
        pass

    # - apiVersion: v1
    # data:
    #     # custom token
    #     token: xxxx
    # kind: Secret
    # Type: Opaque
    # metadata:
    #     creationTimestamp: "2022-07-17T21:18:55Z"
    #     name: parallelstokenfile
    #     namespace: default
    #     resourceVersion: "13504224"
    #     uid: 051e3990-7062-4d69-80dc-24e5df79d9ef
    sec = kubernetes_client.V1Secret()
    sec.metadata = kubernetes_client.V1ObjectMeta(name=token_secret_name, namespace=job_namespace)
    sec.type = 'Opaque'
    sec.data = {'token': tok}
    core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec)

    # - apiVersion: v1
    # data:
    #     # aws credential file
    #     credentials: xxxxx
    # kind: Secret
    # metadata:
    #     creationTimestamp: "2022-07-18T04:37:51Z"
    #     name: awscredsfile
    #     namespace: default
    #     resourceVersion: "13575017"
    #     uid: ca514c11-42c9-4f8b-bdb1-04ec98f59139
    # Type: Opaque
    aws_creds = base64.b64encode(credsfile_contents.encode('utf-8')).decode('utf-8')
    awscredsfilename = 'awscredsfile-' + unique_suffix
    try:
        core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=awscredsfilename)
    except Exception:
        pass
    sec1 = kubernetes_client.V1Secret()
    sec1.metadata = kubernetes_client.V1ObjectMeta(name=awscredsfilename, namespace=job_namespace)
    sec1.type = 'Opaque'
    sec1.data = {'credentials': aws_creds}
    core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec1)

    gce_secret_name = 'gcekeyfile-' + unique_suffix
    gce_keyfile = base64.b64encode(gce_keyfile_contents.encode('utf-8')).decode('utf-8')
    try:
        core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=gce_secret_name)
    except Exception:
        pass
    sec2 = kubernetes_client.V1Secret()
    sec2.metadata = kubernetes_client.V1ObjectMeta(name=gce_secret_name, namespace=job_namespace)
    sec2.type = 'Opaque'
    sec2.data = {'key.json': gce_keyfile}
    core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec2)
    
    hpe_secret_name = 'hpekubeconfig-' + unique_suffix
    # setup creds for HPE.  
    # first delete the current secret
    try:
        core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=hpe_secret_name)
    except Exception:
        pass
    # then create the secret
    # Note: hpe_cluster_config cannot be None.
    hpe_cred_secret_yaml:io.StringIO = io.StringIO(f"""
apiVersion: v1
kind: Secret
type: Opaque
data:
    config: {base64.b64encode(hpe_cluster_config.hpeKubeConfigPrivateNet.encode('utf-8')).decode('utf-8')}
stringData:
    hpeKubeConfigContext: {hpe_cluster_config.hpeKubeConfigContext}
    hpeContainerRegistryUri: {hpe_cluster_config.hpeContainerRegistryUri}    
metadata:
    name: {hpe_secret_name}
    namespace: {job_namespace}
        """)
    res_list:list = kubernetes.utils.create_from_yaml(core_api_instance.api_client, yaml_objects=[yaml.safe_load(hpe_cred_secret_yaml)], namespace=job_namespace, verbose=True)
    logger.info(f"kubernetes.utils.create_from_yaml(): hpe_cred_secret_yaml={hpe_cred_secret_yaml}\nres_list={ res_list }")

    taskinfo_secret_name = 'taskinfo-' + unique_suffix
    try:
        core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=taskinfo_secret_name)
    except Exception:
        pass
    sec3 = kubernetes_client.V1Secret()
    sec3.metadata = kubernetes_client.V1ObjectMeta(name=taskinfo_secret_name, namespace=job_namespace)
    sec3.type = 'Opaque'
    deploy_model_params = {'testkey': 'testval'}
    deploy_model_params_encoded = base64.b64encode(json.dumps(deploy_model_params).encode('utf-8')).decode('utf-8')
    sec3.data = {'taskinfo': deploy_model_params_encoded}
    core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec3)

    # setup iam roles anywhere credentials, if needed
    iam_roles_anywhere_secret_name:str = None
    setup_roles_anywhere:bool = 'iamRolesAnywhereCert' in subs
    if setup_roles_anywhere:
        cert_priv_key:str
        cert_priv_key, _, _ = utils.get_or_renew_and_update_iam_roles_anywhere_certs(cognito_username, subs)
        if not cert_priv_key: raise Exception("Unable to issue certificate.  Check the logs for further details")
        
        iam_roles_anywhere_secret_name = "iam-roles-anywhere-" + unique_suffix
        # pass the secret name as an environment variable to the bootstrap pod
        cmap.data['IAM_ROLES_ANYWHERE_SECRET_NAME'] = iam_roles_anywhere_secret_name
        # do not use the profile [default] since the MLFlow project pod uses [default] in ~/.aws/credentials.  this [default] in ~/.aws/credentials is setup by concurrent_plugin.concurrent_backend.run_eks_job()
        aws_cred_config_file = f"""
[profile subscriber_infinlogs_iam_roles_anywhere]
credential_process = /root/aws_signing_helper credential-process --certificate /root/.aws-iam-roles-anywhere/iamRolesAnywhereCert --private-key /root/.aws-iam-roles-anywhere/iamRolesAnywhereCertPrivateKey --trust-anchor-arn {subs['iamRolesAnyWhereTrustAnchorArn']['S']} --profile-arn  {subs['iamRolesAnywhereProfileArn']['S']} --role-arn {subs['iamRolesAnywhereRoleArn']['S']}
"""
        roles_anywhere_secret_yaml:io.StringIO = io.StringIO(f"""
apiVersion: v1
kind: Secret
type: Opaque
data:
    iamRolesAnywhereCert: {base64.b64encode(subs['iamRolesAnywhereCert']['S'].encode('utf-8')).decode('utf-8')}
    iamRolesAnywhereCertPrivateKey: {base64.b64encode(subs['iamRolesAnywhereCertPrivateKey']['S'].encode('utf-8')).decode('utf-8')}
    awsCredentialConfigFile: {base64.b64encode(aws_cred_config_file.encode('utf-8')).decode('utf-8')}
stringData:
    iamRolesAnyWhereTrustAnchorArn: {subs['iamRolesAnyWhereTrustAnchorArn']['S']}
    iamRolesAnywhereProfileArn: {subs['iamRolesAnywhereProfileArn']['S']}
    iamRolesAnywhereRoleArn: {subs['iamRolesAnywhereRoleArn']['S']}
metadata:
    name: {iam_roles_anywhere_secret_name}
    namespace: {job_namespace}
        """)
        res_list:list = kubernetes.utils.create_from_yaml(core_api_instance.api_client, yaml_objects=[yaml.safe_load(roles_anywhere_secret_yaml)], namespace=job_namespace, verbose=True)
        logger.info(f"kubernetes.utils.create_from_yaml(): roles_anywhere_secret_yaml={roles_anywhere_secret_yaml}\nres_list={res_list}")
    
    v1_volume_mounts:List = [
        kubernetes_client.V1VolumeMount(mount_path='/root/.concurrent', name='parallels-token-file'),
        kubernetes_client.V1VolumeMount(mount_path='/root/.aws', name='aws-creds-file'),
        kubernetes_client.V1VolumeMount(mount_path='/root/.gce', name='gce-key-file'),
        kubernetes_client.V1VolumeMount(mount_path='/root/.taskinfo', name='taskinfo-file'),
        kubernetes_client.V1VolumeMount(mount_path='/root/.kube', name='hpe-secret-volume')
        ]
    if setup_roles_anywhere: 
        v1_volume_mounts.append(kubernetes_client.V1VolumeMount(mount_path='/root/.aws-iam-roles-anywhere', name='iam-roles-anywhere-volume'))
    
    v1_volumes:List = [
        kubernetes_client.V1Volume(name="parallels-token-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=token_secret_name)),
        kubernetes_client.V1Volume(name="aws-creds-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=awscredsfilename)),
        kubernetes_client.V1Volume(name="gce-key-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=gce_secret_name)),
        kubernetes_client.V1Volume(name="taskinfo-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=taskinfo_secret_name)),
        kubernetes_client.V1Volume(name="hpe-secret-volume", secret=kubernetes_client.V1SecretVolumeSource(secret_name=hpe_secret_name))
        ]
    if setup_roles_anywhere: 
        v1_volumes.append(kubernetes_client.V1Volume(name="iam-roles-anywhere-volume", secret=kubernetes_client.V1SecretVolumeSource(secret_name=iam_roles_anywhere_secret_name)))
    
    return v1_volume_mounts, v1_volumes
