from dataclasses import dataclass
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
import json

import utils

logger = logging.getLogger()

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

def _get_deployments(cluster_type, cl, con:Configuration, rv):
    namespace=cl['namespace']
    print('_get_deployments: namespace=' + str(namespace))
    with kubernetes.client.ApiClient(con) as api_client:
        # Create an instance of the API class
        api_instance = kubernetes.client.AppsV1Api(api_client)
        pretty = True
        allow_watch_bookmarks = False
        _continue = None
        field_selector = None
        label_selector = None
        limit = 56
        timeout_seconds = 56
        watch = False
        try:
            api_response = api_instance.list_namespaced_deployment(namespace, pretty=pretty, allow_watch_bookmarks=allow_watch_bookmarks,
                                                                    _continue=_continue, field_selector=field_selector,
                                                                    label_selector=label_selector, limit=limit,
                                                                    timeout_seconds=timeout_seconds, watch=watch)
            #print(api_response)
            items = api_response.items
            for item in items:
                try:
                    name = item.metadata.name
                    containers = item.spec.template.spec.containers
                    cs = []
                    for container in containers:
                        ports = container.ports
                        all_ports = []
                        for port in ports:
                            ps = {}
                            ps['container_port'] = port.container_port
                            if hasattr(port, 'host_ip') and port.host_ip:
                                ps['host_ip'] = port.host_ip
                            if hasattr(port, 'host_port') and port.host_port != None:
                                ps['host_port'] = str(port.host_port)
                            if hasattr(port, 'protocol'):
                                ps['protocol'] = str(port.protocol)
                            all_ports.append(ps)
                        cs.append({"name": container.name, "ports": all_ports})
                    rv.append({'name': name,
                                'containers': cs,
                                'cluster_type': f"{cluster_type}",
                                'cluster_name': f"{cl['cluster_name']}",
                                'namespace': f"{namespace}"})
                except Exception as e:
                    traceback.print_exc()
                    print(f"Ignoring exception parsing item {item}")
        except ApiException as e:
            print("Exception when calling AppsV1Api->list_namespaced_deployment: %s\n" % e)
    return rv

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

def list_gke_deployments_from_cluster(cl, service_conf, cognito_username, groups, subs, rv):
    gke_cluster_name = cl['cluster_name']
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
    _get_deployments('gke', cl, configuration, rv)

def list_eks_deployments_from_cluster(cl, service_conf, cognito_username, groups, subs, rv):
    eks_region = cl['eks_region']
    eks_role = cl['eks_role']
    eks_role_ext = cl['eks_role_ext']

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
    print('list_eks_deployments_from_cluster: describe_cluster res=' + str(resp))
    endpoint = resp['cluster']['endpoint']
    print('list_eks_deployments_from_cluster: endpoint=' + str(endpoint))
    cert_auth = resp['cluster']['certificateAuthority']['data']
    print('list_eks_deployments_from_cluster: cert_auth=' + str(cert_auth))
    cluster_arn = resp['cluster']['arn']
    print('list_eks_deployments_from_cluster: cluster_arn=' + str(cluster_arn))

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
    _get_deployments('eks', cl, con, rv)

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

def list_hpe_deployments_from_cluster(cl, service_conf, cognito_username, groups, subs, rv):
    hpe_cluster_conf:HpeClusterConfig = _lookup_hpe_cluster_config(cognito_username, groups, cl['cluster_name'], subs)
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
    

def list_depl_internal(service_conf, cognito_username, groups, subs, rv):
    kube_clusters = query_user_accessible_clusters(cognito_username, groups)
    for cl in kube_clusters:
        if cl['cluster_type'] == 'EKS':
            list_eks_deployments_from_cluster(cl, service_conf, cognito_username, groups, subs, rv)
        elif cl['cluster_type'] == 'GKE':
            list_gke_deployments_from_cluster(cl, service_conf, cognito_username, groups, subs, rv)
        elif cl['cluster_type'] == HpeClusterConfig.HPE_CLUSTER_TYPE:
            list_hpe_deployments_from_cluster(cl, service_conf, cognito_username, groups, subs, rv)
        else:
            print(f"Warning: Unknown cluster type {cl['cluster_type']}")

def list_deployments(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)
    success, status, subs = get_subscriber_info(cognito_username) 
    if not success: return respond(ValueError(status))
    
    success, status, service_conf = get_service_conf()
    if not success: return respond(ValueError(status))

    rv = []
    list_depl_internal(service_conf, cognito_username, groups, subs, rv)
    print(f"list_deployments: {rv}")
    return respond(None, {'deployments': rv})
