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
from list_deployments import list_depl_internal

import utils
# pylint: disable=logging-not-lazy,bad-indentation,broad-except,logging-fstring-interpolation

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

def create_endpoint(event, context):
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
    # example: '{"name": ""}
    item = json.loads(body)
    deployments = []
    list_depl_internal(service_conf, cognito_username, groups, subs, deployments)
    print(f"create_endpoint: deployments={deployments}")
    for depl in deployments:
        if depl['name'] == item['name']:
            if depl['cluster_type'] == 'eks':
                return create_endpoint_eks(depl, service_conf, cognito_username, groups, subs)
            elif depl['cluster_type'] == 'gke':
                return create_endpoint_gke(depl, service_conf, cognito_username, groups, subs)
            elif depl['cluster_type'] == HpeClusterConfig.HPE_CLUSTER_TYPE:
                return create_endpoint_hpe(depl, service_conf, cognito_username, groups, subs)
            else:
                print(f"Warning: Unknown cluster type {depl['cluster_type']}")
                return respond(ValueError(f"Unknown cluster type {depl['cluster_type']}"))
    return respond(None, {'status': f"Failed. Unable to find deployment named {item['name']}"})

def _create_k8s_endpoint(backend_type, endpoint, cert_auth, cluster_arn, deployment,
                        eks_access_key_id, eks_secret_access_key, eks_session_token, ecr_type, ecr_region,
                        ecr_access_key_id, ecr_secret_access_key, ecr_session_token, ecr_aws_account_id,
                        gke_project_id, gke_creds, hpe_cluster_config:HpeClusterConfig,
                        cognito_username:str, subs:dict, con:Configuration):
    deployment_name = deployment['name']
    print(f"_create_k8s_endpoint: Entered. deployment={deployment}")
    api_instance = kubernetes_client.CoreV1Api(api_client=api_client.ApiClient(configuration=con))

    run_id = deployment_name[25:]
    body = kubernetes.client.V1Service()
    metadata = kubernetes_client.V1ObjectMeta()
    metadata.name = f"mlflow-deploy-endpoint-{run_id}"
    print(f"_create_k8s_endpoint: endpoint name={metadata.name}")
    body.metadata = metadata

    our_port = deployment['containers'][0]['ports'][0]
    port = kubernetes_client.V1ServicePort(port=our_port['container_port'])
    if 'protocol' in our_port:
        port.protocol = our_port['protocol']
        print(f"Using protocol {port.protocol} from our_port")
    else:
        port.protocol = 'TCP'
        print("Using defaul protocol TCP")
    print(f"k8s V1ServicePort={port}")

    spec = kubernetes.client.V1ServiceSpec()
    spec.ports = [port]
    spec.selector = {"app": f"mlflow-deploy-{run_id}"}
    spec.type = "LoadBalancer"
    body.spec = spec
    try:
        api_instance.create_namespaced_service(namespace=deployment['namespace'], body=body)
    except ApiException as e:
        print(f"While calling create_namespaced_service, caught {e}")
        return False
    return True

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


def create_endpoint_gke(deployment, service_conf, cognito_username, groups, subs):
    logger.info("create_endpoint_gke: Running in kube. deployment=" + str(deployment))
    gke_cluster_name = deployment['cluster_name']
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

    success = _create_k8s_endpoint('gke', response.endpoint, response.master_auth.cluster_ca_certificate, None,
                    deployment, None, None, None, None, None, None, None, None, None,
                    gke_project_id, gke_creds, empty_hpe_cluster_config, cognito_username, subs, configuration)
    os.remove(creds_file_path)
    if success:
        return respond(None, {})
    else:
        return respond(ValueError(f"Error creating endpoint for deployment {deployment}"))

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
    
    _create_k8s_endpoint(HpeClusterConfig.HPE_CLUSTER_TYPE, endpoint=None, cert_auth=None, cluster_arn=None, item=reqbody, eks_access_key_id=None, eks_secret_access_key=None, eks_session_token=None, ecr_type=None, ecr_region=None, ecr_access_key_id=None, ecr_secret_access_key=None, ecr_session_token=None, ecr_aws_account_id=None, gke_project_id=None, gke_creds=None, hpe_cluster_config=hpe_cluster_conf, cognito_username=cognito_username, subs=subs, con=kube_config)
    
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

    _create_k8s_endpoint('eks', endpoint, cert_auth, cluster_arn, item, eks_access_key_id, eks_secret_access_key, eks_session_token,
                        ecr_type, ecr_region, ecr_access_key_id, ecr_secret_access_key, ecr_session_token, ecr_aws_account_id,
                        None, None, empty_hpe_cluster_config, cognito_username, subs, con)
    return respond(None, {})
