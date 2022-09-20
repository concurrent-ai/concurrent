
import json
import os
import logging
import boto3
import tempfile
import uuid
import time
import base64
from google.cloud import container_v1
import google.auth
import google.auth.transport.requests
from kubernetes import client as kubernetes_client
from tempfile import NamedTemporaryFile, mkstemp

from utils import get_service_conf, get_subscriber_info, get_cognito_user, get_custom_token
from kube_clusters import query_kube_clusters
from kubernetes import client, config, dynamic
from kubernetes.client import models as k8s
from kubernetes.client import api_client, Configuration
from kubernetes.client.rest import ApiException

# pylint: disable=logging-not-lazy,bad-indentation,broad-except

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def respond(err, res=None):
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

def run_project(event, context):
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
    
    success, status, service_conf = get_service_conf()

    body = event['body']
    item = json.loads(body)

    #Inject Parallels token in the body
    queue_message_uuid, token = get_custom_token(cognito_username, groups)
    item['parallels_token']="Custom {0}:{1}".format(queue_message_uuid, token)

    logger.info('msg payload item=' + str(item))

    if item.get('instance_type') == 'eks':
        ##TODO: UI curently sends instance type
        backend_type = 'eks'
    elif item.get('instance_type') == 'gke':
        backend_type = 'gke'
    else:
        backend_type = item.get('backend_type')

    if backend_type == 'eks':
        return run_project_eks(cognito_username, context, subs, item, service_conf)
    if backend_type == 'gke':
        return run_project_gke(cognito_username, context, subs, item, service_conf)
    else:
        err = 'run_project: Error. Unknown backend type ' + backend_type
        logger.error(err)
        return respond(ValueError(err))


def lookup_gke_cluster_config(cognito_username, kube_cluster_name, subs):
    # First lookup user specific cluster
    gke_location_type, gke_location, gke_project_id, gke_creds = None, None, None, None
    kube_clusters = query_kube_clusters(cognito_username)
    for cl in kube_clusters:
        if cl['cluster_name'] == kube_cluster_name and cl['cluster_type'] == 'GKE':
            logger.info("Found user's cluser " + kube_cluster_name)
            return cl['gke_location_type'], cl['gke_location'], cl['gke_project_id'], cl['gke_creds']

    logger.info("Use cluster info for subscriber")
    # Fall back to subscriber's cluster
    gke_location = subs['gke_location']['S']
    gke_location_type = subs['gke_location_type']['S']
    gke_project_id = subs['gke_project']['S']
    gke_creds = subs['gke_creds']['S']

    return gke_location_type, gke_location, gke_project_id, gke_creds


def run_project_gke(cognito_username, context, subs, item, service_conf):
    logger.info("run_project_gke: Running in kube. item=" + str(item) + ', service_conf=' + str(service_conf))
    if not 'kube_context' in item:
        return respond(ValueError('Project Backend Configuration must include kube_context'))

    gke_cluster_name = item['kube_context']
    gke_location_type, gke_location, gke_project_id, gke_creds \
        = lookup_gke_cluster_config(cognito_username, gke_cluster_name, subs)

    fd, creds_file_path = mkstemp(suffix='.json', text=True)
    with open(creds_file_path, 'w') as tmp_creds_file:
        print('{}'.format(gke_creds), file=tmp_creds_file)
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_file_path
    creds, project = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
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

    cfg = kubernetes_client.ApiClient(configuration)
    k8s_client = kubernetes_client.BatchV1Api(cfg)
    ret = k8s_client.list_job_for_all_namespaces()
    logger.info(ret)

    _kickoff_bootstrap('gke', response.endpoint, response.master_auth.cluster_ca_certificate, None,
                    item, None, None, None, None, None, None, None, None, None,
                    gke_project_id, gke_creds, cognito_username, subs, configuration)
    os.remove(creds_file_path)
    return respond(None, {})

def _create_prio_class(con, name, val, global_default):
    api_resp = None
    api_instance = kubernetes_client.SchedulingV1Api(api_client=api_client.ApiClient(configuration=con))
    try:
        api_resp = api_instance.read_priority_class(name)
    except ApiException as ae:
        print('While reading ' + str(name) + ', caught ' + str(ae))
        _do_create_prio_class(con, name, val, global_default)
    else:
        print('Successfully read priority class ' + str(name) + ': ' + str(api_resp))
        return

def _do_create_prio_class(con, name, val, global_default):
    api_resp = None
    api_instance = kubernetes_client.SchedulingV1Api(api_client=api_client.ApiClient(configuration=con))
    body = kubernetes_client.V1PriorityClass(value=val, metadata=kubernetes_client.V1ObjectMeta(name=name), global_default=global_default)
    try:
        api_resp = api_instance.create_priority_class(body)
    except ApiException as ae:
        print('While creating ' + str(name) + ', caught ' + str(ae))
    else:
        print('Successfully created priority class ' + str(name) + ': ' + str(api_resp))

def _create_prio_classes(con):
    _create_prio_class(con, 'parallels-high-prio', 1000, False)
    _create_prio_class(con, 'parallels-lo-prio', 100, True)

def _kickoff_bootstrap(backend_type, endpoint, cert_auth, cluster_arn, item,
                        eks_access_key_id, eks_secret_access_key, eks_session_token, ecr_type, ecr_region,
                        ecr_access_key_id, ecr_secret_access_key, ecr_session_token, ecr_aws_account_id,
                        gke_project_id, gke_creds, cognito_username, subs, con):
    _create_prio_classes(con)
    run_id = item['run_id']
    canonical_nm = 'mlflow-project-' + run_id + "-" + str(int(time.time() * 1000))
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
    cmap.data['MLFLOW_PARALLELS_URI'] = item['MLFLOW_PARALLELS_URI']
    cmap.data['MLFLOW_TRACKING_URI'] = item['MLFLOW_TRACKING_URI']
    cmap.data['MLFLOW_RUN_ID'] = run_id
    cmap.data['NAMESPACE'] = namespace
    if backend_type == 'eks':
        cmap.data['ECR_TYPE'] = ecr_type
        cmap.data['ECR_REGION'] = ecr_region
    elif backend_type == 'gke':
        cmap.data['PROJECT_ID'] = gke_project_id
    if ecr_aws_account_id:
        cmap.data['ECR_AWS_ACCOUNT_ID'] = ecr_aws_account_id

    if 'input_data_spec' in item:
        run_input_spec_map = {run_id: json.loads(item['input_data_spec'])}
    elif 'run_input_spec_map' in item:
        run_input_spec_map = json.loads(item['run_input_spec_map'])
    else:
        run_input_spec_map = {run_id: []}

    run_input_spec_map_encoded = base64.b64encode(json.dumps(run_input_spec_map).encode('utf-8'),
                                                  altchars=None).decode('utf-8')

    if 'xformname' in item:
        cmap.data['XFORMNAME'] = item['xformname']

    if 'periodic_run_name' in item:
        cmap.data['PERIODIC_RUN_NAME'] = item['periodic_run_name']
    if 'dagid' in item:
        cmap.data['DAGID'] = item['dagid']
    if 'dag_execution_id' in item:
        cmap.data['DAG_EXECUTION_ID'] = item['dag_execution_id']
    if 'original_node' in item:
        cmap.data['ORIGINAL_NODE_ID'] = item['original_node']

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
    if "resources.requests.nvidia.com/gpu" in item:
        gpu_count = item['resources.requests.nvidia.com/gpu']
        if int(gpu_count) > 0:
            cmap.data['RESOURCES_REQUESTS_NVIDIA_COM_GPU'] = gpu_count
    if 'params' in item:
        print('params=' + str(item['params']))
        cmap.data['PROJECT_PARAMS'] = base64.b64encode(json.dumps(item['params']).encode('utf-8'), altchars=None).decode('utf-8')
    else:
        print('No params')
    if 'parent_run_id' in item:
        cmap.data['PARENT_RUN_ID'] = item['parent_run_id']
    if 'last_in_chain_of_xforms' in item:
        cmap.data['LAST_IN_CHAIN_OF_XFORMS'] = item['last_in_chain_of_xforms']
    if 'kube_job_template_contents' in item:
        cmap.data['KUBE_JOB_TEMPLATE_CONTENTS'] = item['kube_job_template_contents']
    if 'git_commit' in item:
        cmap.data['GIT_COMMIT'] = item['git_commit']
    if 'xform_path' in item:
        cmap.data['XFORM_PATH'] = item['xform_path']
    if 'additionalPackages' in subs:
        cmap.data['ADDITIONAL_PACKAGES'] = subs['additionalPackages']['S']
    if 'additionalImports' in subs:
        cmap.data['ADDITIONAL_IMPORTS'] = subs['additionalImports']['S']
    api_instance = kubernetes_client.CoreV1Api(api_client=api_client.ApiClient(configuration=con))
    api_instance.create_namespaced_config_map(namespace=namespace, body=cmap)

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
    else:
        credsfile_contents = '# AWS Credentials file unused for ' + backend_type
        gce_keyfile_contents = gke_creds
    volume_mounts, volumes = setup_secrets(api_instance, namespace, tokfile_contents, credsfile_contents,
                                           gce_keyfile_contents, run_input_spec_map_encoded)

    if 'bootstrapImage' in subs:
        bootstrap_image = subs['bootstrapImage']['S']
    else:
        bootstrap_image = 'public.ecr.aws/k7c5t9s7/parallels-eks-bootstrap'

    pod = k8s.V1Pod(
        api_version='v1',
        metadata=k8s.V1ObjectMeta(name=canonical_nm, namespace=namespace),
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name=canonical_nm,
                    image = bootstrap_image,
                    env_from=[
                        k8s.V1EnvFromSource(
                            config_map_ref=k8s.V1ConfigMapEnvSource(name=canonical_nm)
                        )
                    ],
                    env=[
                        k8s.V1EnvVar(name='MY_POD_NAME', 
                            value_from=k8s.V1EnvVarSource(
                                field_ref=k8s.V1ObjectFieldSelector(
                                    field_path='metadata.name'
                                )
                            )
                        )
                    ],
                    security_context=k8s.V1SecurityContext(privileged=True),
                    volume_mounts=volume_mounts,
                    resources = k8s.V1ResourceRequirements(requests={'cpu': '500m', 'memory': '512M'}, limits={'cpu': '1000m', 'memory': '2048M'})
                )
            ],
            restart_policy='Never',
            priority_class_name='parallels-high-prio',
            volumes=volumes,
            # service_account_name='infinstor-serviceaccount-' + namespace
            service_account_name='k8s-serviceaccount-for-parallels-' + namespace
        )
    )
    try:
        arv = api_instance.create_namespaced_pod(namespace=namespace,body=pod)
    except Exception as ex:
        logger.error('kickoff_bootstrap: create_namespaced_pod of bootstrap caught ' + str(ex))
    else:
        logger.info('kickoff_bootstrap: create_namespaced_pod of bootstrap returned api_ver=' + str(arv.api_version)
            + ', kind=' + str(arv.kind) + ', metadata=' + str(arv.metadata)
            + ', spec=' + str(arv.spec) + ', status=' + str(arv.status))


def lookup_eks_cluster_config(cognito_username, kube_cluster_name, subs):
    # First lookup user specific cluster
    eks_region, eks_role, eks_role_ext = None, None, None
    kube_clusters = query_kube_clusters(cognito_username)
    for cl in kube_clusters:
        if cl['cluster_name'] == kube_cluster_name and cl['cluster_type'] == 'EKS':
            logger.info("Found user's cluser " + kube_cluster_name)
            return cl['eks_region'], cl['eks_role'], cl['eks_role_ext']

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

    return eks_region, eks_role, eks_role_ext


def run_project_eks(cognito_username, context, subs, item, service_conf):
    logger.info("run_project: Running in kube. item=" + str(item) + ', service_conf=' + str(service_conf))
    if not 'kube_context' in item:
        return respond(ValueError('Project Backend Configuration must include kube_context'))
    kube_cluster_name = item['kube_context']

    eks_access_key_id = None
    eks_secret_access_key = None
    eks_session_token = None

    eks_region, eks_role, eks_role_ext = lookup_eks_cluster_config(cognito_username, kube_cluster_name, subs)
    ecr_role = None
    ecr_role_ext = None
    ecr_type = None
    ecr_region = None
    ecr_aws_account_id = None

    if 'ecrRole' in subs:
        ecr_role = subs['ecrRole']['S']
    if 'ecrRoleExt' in subs:
        ecr_role_ext = subs['ecrRoleExt']['S']
    if 'ecrType' in subs:
        ecr_type = subs['ecrType']['S']
    if 'ecrRegion' in subs:
        ecr_region = subs['ecrRegion']['S']
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
    cdir = tempfile.mkdtemp();
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
    print(open(os.path.join(cdir, 'config')).read())
    con = type.__call__(Configuration)
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
        err = 'run_project_eks: ecr role, ext, region and type must be specified'
        logger.error(err)
        return respond(ValueError(err))

    _kickoff_bootstrap('eks', endpoint, cert_auth, cluster_arn, item, eks_access_key_id, eks_secret_access_key, eks_session_token,
                        ecr_type, ecr_region, ecr_access_key_id, ecr_secret_access_key, ecr_session_token, ecr_aws_account_id,
                        None, None, cognito_username, subs, con)
    return respond(None, {})


def setup_secrets(core_api_instance, job_namespace, tokfile_contents, credsfile_contents,
                  gce_keyfile_contents, run_input_spec_map_encoded):
  tok = base64.b64encode(tokfile_contents.encode('utf-8')).decode('utf-8')
  unique_suffix = str(uuid.uuid4())
  token_secret_name = 'parallelstokenfile-' + unique_suffix
  try:
      core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=token_secret_name)
  except:
      pass
  sec = kubernetes_client.V1Secret()
  sec.metadata = kubernetes_client.V1ObjectMeta(name=token_secret_name, namespace=job_namespace)
  sec.type = 'Opaque'
  sec.data = {'token': tok}
  core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec)

  aws_creds = base64.b64encode(credsfile_contents.encode('utf-8')).decode('utf-8')
  awscredsfilename = 'awscredsfile-' + unique_suffix
  try:
      core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=awscredsfilename)
  except:
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
  except:
      pass
  sec2 = kubernetes_client.V1Secret()
  sec2.metadata = kubernetes_client.V1ObjectMeta(name=gce_secret_name, namespace=job_namespace)
  sec2.type = 'Opaque'
  sec2.data = {'key.json': gce_keyfile}
  core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec2)

  taskinfo_secret_name = 'taskinfo-' + unique_suffix
  try:
      core_api_instance.delete_namespaced_secret(namespace=job_namespace, name=taskinfo_secret_name)
  except:
      pass
  sec3 = kubernetes_client.V1Secret()
  sec3.metadata = kubernetes_client.V1ObjectMeta(name=taskinfo_secret_name, namespace=job_namespace)
  sec3.type = 'Opaque'
  sec3.data = {'taskinfo': run_input_spec_map_encoded}
  core_api_instance.create_namespaced_secret(namespace=job_namespace, body=sec3)

  return \
    [
      kubernetes_client.V1VolumeMount(mount_path='/root/.mlflow-parallels', name='parallels-token-file'),
      kubernetes_client.V1VolumeMount(mount_path='/root/.aws', name='aws-creds-file'),
      kubernetes_client.V1VolumeMount(mount_path='/root/.gce', name='gce-key-file'),
      kubernetes_client.V1VolumeMount(mount_path='/root/.taskinfo', name='taskinfo-file')
    ], [
      kubernetes_client.V1Volume(name="parallels-token-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=token_secret_name)),
      kubernetes_client.V1Volume(name="aws-creds-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=awscredsfilename)),
      kubernetes_client.V1Volume(name="gce-key-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=gce_secret_name)),
      kubernetes_client.V1Volume(name="taskinfo-file", secret=kubernetes_client.V1SecretVolumeSource(secret_name=taskinfo_secret_name))
    ]
