import socket
import time
import os
from concurrent_plugin.infinfs import infinmount
import json
import yaml
from mlflow.tracking import MlflowClient
import psutil
from concurrent_plugin.concurrent_backend import MOUNT_SERVICE_READY_MARKER_FILE
import concurrent_plugin.utils
import logging
import requests
import subprocess
# importing it as kubernetes.client since 'client' is used in the code in some places as the Mlflow client.  this mlflow 'client' conflicts with 'from kubernetes import client'.  Need to cleanup.
import kubernetes.client
from kubernetes import client, config
import dpath
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


FUSE_DEBUG_FILE = '/tmp/fuse_debug.log'
VERBOSE = False

mlflow_run_status = None

def parse_mount_request(data):
    req = json.loads(data.decode('utf-8'))
    if req['use_cache'].lower() == 'false':
        use_cache = False
    else:
        use_cache = True
    if req['shadow_path'].lower() == 'none':
        shadow_path = None
    else:
        shadow_path = req['shadow_path']
    return req['mount_path'], req['mount_spec'], shadow_path, use_cache


def print_info(*args):
    print(str(datetime.utcnow()), *args, flush=True)

def mount_service_ready():
    ##Create empty marker file
    if not os.path.exists(MOUNT_SERVICE_READY_MARKER_FILE):
        with open(MOUNT_SERVICE_READY_MARKER_FILE, "w"):
            pass

def read_token(token_file):
    with open(token_file, 'r') as tfh:
        token_file_content = tfh.read()
        for token_line in token_file_content.splitlines():
            if token_line.startswith('Token='):
                return token_line[6:]
    return None

def launch_dag_controller():
    infinstor_token = read_token('/root/.concurrent/token')
    mlflow_parallels_uri = os.environ['MLFLOW_CONCURRENT_URI']
    dag_execution_id = os.environ['DAG_EXECUTION_ID']
    dagid = os.environ['DAGID']
    periodic_run_name = os.environ.get('PERIODIC_RUN_NAME')
    periodic_run_frequency = os.getenv('PERIODIC_RUN_FREQUENCY')
    periodic_run_start_time = os.getenv('PERIODIC_RUN_START_TIME')
    periodic_run_end_time = os.getenv('PERIODIC_RUN_END_TIME')

    execute_dag_url = mlflow_parallels_uri.rstrip('/') + '/api/2.0/mlflow/parallels/execdag'
    logger.info(execute_dag_url)
    headers = {'Content-Type': 'application/json', 'Authorization': infinstor_token}
    body = {'dagid': dagid, 'dag_execution_id': dag_execution_id, "periodic_run_name": periodic_run_name}
    if periodic_run_frequency:
      body['periodic_run_frequency'] = periodic_run_frequency
    if periodic_run_start_time:
      body['periodic_run_start_time'] = periodic_run_start_time
    if periodic_run_end_time:
      body['periodic_run_end_time'] = periodic_run_end_time
    attempts_left = max_attempts = 3
    while attempts_left > 0:
        attempts_left -= 1
        try:
            response = requests.post(execute_dag_url, json=body, headers = headers)
            logger.info(f"DAG Controller response: {response}")
            return
        except Exception as ex:
            logger.warning(str(ex))
            print(f'Exception in dag controller call, retry {attempts_left} more times')
            if attempts_left > 0:
                ##wait before retrying
                time.sleep(10 * 2 ** (max_attempts - attempts_left))
    else:
        raise Exception("Dag Controller launch failed multiple times")


def upload_logs_for_pod(k8s_client:kubernetes.client.CoreV1Api, run_id, pod_name, pod_namespace, tmp_log_file, container_name):
    try:
        client = MlflowClient()
        client.log_artifact(run_id, tmp_log_file, artifact_path='.concurrent/logs')
    except Exception as ex:
        logger.warning("Failed upload logs for {}, {}: {}".format(run_id, pod_name, ex))
        
def add_logs_for_pod(k8s_client:kubernetes.client.CoreV1Api, run_id, pod_name, pod_namespace, log_file, tmp_log_file, container_name):
    try:
        # possible fix if only partial logs are read and full logs can't be read. Note that using follow=True for a running pod may make it wait forever??
        # https://github.com/kubernetes-client/python/issues/199: Passing follow=True to read_namespaced_pod_log makes it never return #199
        pod_logs = k8s_client.read_namespaced_pod_log(pod_name, pod_namespace, container=container_name)
        logger.info(type(pod_logs))
        with open(tmp_log_file, "w") as fh:
            fh.write(pod_logs)
        upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, tmp_log_file,
                                container_name=container_name)
        # Merging code
        with open(log_file,'r+' if os.path.isfile(log_file) else 'w+') as f1,\
             open(tmp_log_file,'r') as f2:
                file1 = f1.readlines()
                file2 = f2.readlines()
                if len(file1)<=len(file2) and file1 == file2[:len(file1)]:          #check the file1 is in file2
                    f1.writelines(file2[len(file1):])
                    
                elif file1 != [] and file1[-1] in file2:                            #check the common lines in both files
                    index = 0
                    ind = file2.index(file1[-1])+1  
                    while ind<=len(file2):                                          #If there is any common lines,it will find the index and direct you    
                        if file1[len(file1)-ind:] == file2[:ind]:
                            index = ind                                   
                        if file1[-1] in file2[ind:]:                                
                            ind += file2[ind:].index(file1[-1])+1           
                        else:
                            break
                    f1.writelines(file2[index:])                                    #If there is common line,merge file1 and file2
                            
                else:
                    f1.writelines(file2)                                            #If there is no common line,then append file1 and file2
                    
    except Exception as ex:
        logger.warning("Failed to fetch logs for {}, {}: {}".format(run_id, pod_name, ex))
        return


def update_mlflow_run(run_id, status):
    logger.info(f"update_mlflow_run(): updating mlflow run-id={run_id} with status={status}")
    client = MlflowClient()
    client.set_terminated(run_id, status)

def log_describe_pod(k8s_client:kubernetes.client.CoreV1Api, run_id, pod_name, pod_namespace, pod_info:kubernetes.client.V1Pod):
    describe_file = "/tmp/describe-" + pod_name + ".txt"
    try:
        events:kubernetes.client.V1EventList = k8s_client.list_namespaced_event(pod_namespace, field_selector=f'involvedObject.name={pod_name}')
        with open(describe_file, "w") as fh:
            pod_info_dict:dict = pod_info.to_dict()
            # remove metadata/managed_fields key
            if pod_info_dict.get('metadata') and pod_info_dict.get('metadata').get('managed_fields'): pod_info_dict['metadata'].pop('managed_fields')            
            concurrent_plugin.utils.filter_empty_in_dict_list_scalar(pod_info_dict)
            fh.write(yaml.safe_dump(pod_info_dict))
            
            events_dict:dict = events.to_dict()
            # api_version: v1
            # kind: EventList
            # metadata:
            #   resource_version: '292715'
            # items:            
            # - count: 1
            #   first_timestamp: 2023-02-22 05:17:20+00:00
            #   involved_object:
            #       api_version: v1
            #       field_path: spec.containers{sidecar-35-16770430018230000000003}
            #       kind: Pod
            #       name: bird-species-2023-02-22-05-17-19-492406-692lg
            #       namespace: parallelsns
            #       resource_version: '106734654'
            #       uid: 008a2e12-b37c-44ed-963f-c9104ccadb4b
            #   last_timestamp: 2023-02-22 05:17:20+00:00
            #   message: Created container sidecar-35-16770430018230000000003
            #   metadata:
            #       creation_timestamp: 2023-02-22 05:17:20+00:00
            #       managed_fields:
            #       - api_version: v1
            #       fields_type: FieldsV1
            #       manager: kubelet
            #       operation: Update
            #       time: 2023-02-22 05:17:20+00:00
            #       name: bird-species-2023-02-22-05-17-19-492406-692lg.17460dc286d42b11
            #       namespace: parallelsns
            #       resource_version: '292711'
            #       uid: 0d95e5e0-85a5-4bf7-8616-dc4eb586fb64
            #   reason: Created
            #   source:
            #       component: kubelet
            #       host: gke-isstage23-cluster-pool-2-vcpu-8gb-43f4db71-x4r5
            #   type: Normal
            # 
            # remove unwanted fields from the eventList
            for path_to_del in '/metadata/managed_fields','/items/*/metadata', '/items/*/involved_object':
                try:
                    # Given a obj, delete all elements that match the glob.  Returns the number of deleted objects. Raises PathNotFound if no paths are found to delete.
                    dpath.delete(events_dict, path_to_del)
                except dpath.PathNotFound as e:
                    print(f"log_describe_pod(): path_to_del={path_to_del}; exception={e}; ignoring exception and continuing..")
            concurrent_plugin.utils.filter_empty_in_dict_list_scalar(events_dict)
            fh.write(yaml.safe_dump(events_dict))
            
        client = MlflowClient()
        client.log_artifact(run_id, describe_file, artifact_path='.concurrent/logs')
    except Exception as ex:
        logger.warning('Failed to log describe pod, try again later: ' + str(ex))
        return

def _fetch_upload_pod_status_logs(k8s_client:client.CoreV1Api, run_id, pod_name, pod_namespace, log_suffix:int):
    try:
        pod_info:client.V1Pod = k8s_client.read_namespaced_pod(pod_name, pod_namespace)
        if pod_info.spec.containers[1].name.startswith('sidecar-'):
            sidecar_index = 1
            task_index = 0
        else:
            sidecar_index = 0
            task_index = 1
        task_container_name = pod_info.spec.containers[task_index].name
        side_car_container_name = pod_info.spec.containers[sidecar_index].name
        log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
        add_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/run-logs.txt", f"/tmp/run-logs-{log_suffix}.txt",
                            container_name=task_container_name)
        add_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/sidecar-logs.txt", f"/tmp/sidecar-logs-{log_suffix}.txt",
                            container_name=side_car_container_name)
        # status:
        #   conditions:
        #   - lastProbeTime: null
        #     .
        #     .
        #   containerStatuses:
        #   - containerID: containerd://9e180784bc5b47d294c022e055b36de7b11b8f297740580ae44ba69b5c56a6b7
        #     .
        #     .
        #     name: sidecar-xxxx
        #     state:
        #       running:
        #         startedAt: "2023-05-26T06:38:17Z"
        #   - containerID: containerd://23c749e123d44b928429cf4193108976f2f479ad4a830b1745e894a2bb67a34f
        #     .
        #     .
        #     name: userbucket-xxxx
        #     state:
        #       terminated:
        #         containerID: containerd://23c749e123d44b928429cf4193108976f2f479ad4a830b1745e894a2bb67a34f
        #         exitCode: 0
        #         .
        #         .
        pod_info_status = pod_info.status
        container_statuses = pod_info_status.container_statuses
        # recompute task_index and sidecar_index for the array 'status/container_statuses'.  Earlier computed index using 'spec/containers' will not always be valid for this array .
        task_index=0; sidecar_index=1
        if container_statuses[0].name.startswith('sidecar-'): sidecar_index=0; task_index=1
        task_cont_status = container_statuses[task_index]
        task_container_state = task_cont_status.state
        if task_container_state.running:
            print(f"Task container is in running state. Continuing to loop")
            return True
        elif task_container_state.terminated:
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/run-logs.txt",
                                container_name=task_container_name)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/sidecar-logs.txt",
                                container_name=side_car_container_name)
            print(f"Task container is in terminated state. Exiting loop")
            return False
        elif task_container_state.waiting:
            print(f"Task container is in waiting state. Continuing to loop")
            return True
        else:
            print(f"Task container is in unknown state. Continuing to loop")
            return True
    except Exception as ex:
        print(f"_fetch_upload_pod_status_logs: caught {ex}. Continuing to loop")
        return True # continue looping

def get_task_exit_code(k8s_client, pod_name, pod_namespace, num_attempt=1):
    max_attempts = 3
    pod_info:client.V1Pod = k8s_client.read_namespaced_pod(pod_name, pod_namespace)
    try:
        # see yaml further above for pod/status/containter_statuses structure
        if pod_info.status.container_statuses[1].name.startswith('sidecar-'):
            exitCode = pod_info.status.container_statuses[0].state.terminated.exit_code
        else:
            exitCode = pod_info.status.container_statuses[1].state.terminated.exit_code
        logger.info("Task container finished with exitCode " + str(exitCode))
        return exitCode
    except Exception as ex:
        logger.error("Exception in getting exit code " + str(ex))
        logger.error("Trying {0} more time(s)".format(max_attempts-num_attempt))
        if num_attempt < max_attempts:
            time.sleep(5* 2**num_attempt)
            return get_task_exit_code(k8s_client, pod_name, pod_namespace, num_attempt=num_attempt+1)
        else:
            return -1


if __name__ == '__main__':
    print_info("Starting..")
    HOST = "127.0.0.1"
    PORT = 7963
    last_upload_time = time.time()
    start_time = time.time()
    run_id = os.getenv('MLFLOW_RUN_ID')
    try:
        print("Environment #", os.environ)
        config.load_incluster_config()
        print('Setting k8s client configuration item retries to 10', flush=True)
        kubernetes.client.configuration.retries = 10
        k8s_client:client.CoreV1Api = client.CoreV1Api()
        pod_name = os.getenv('MY_POD_NAME')
        pod_namespace = os.getenv('MY_POD_NAMESPACE')
        dag_execution_id = os.getenv('DAG_EXECUTION_ID')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(15)
            s.bind((HOST, PORT))
            print('Mount/Monitor service starting for runid {0}, and podname {1}'.format(run_id, pod_name), flush=True)
            print('Listening on port {}:{}'.format(HOST, PORT), flush=True)
            s.listen()
            try:
                mount_service_ready()
            except Exception as ex:
                print(f"mount_service: Caught {ex} while marking mount service ready. Ignoring", flush=True)
            i = 0
            while True:
                print_info('Waiting for request..')
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    print_info('accept timed out')
                    pass
                else:
                    with conn:
                        print_info(f"Connected by {addr}")
                        data = conn.recv(1024*16)
                        if not data:
                            time.sleep(1)
                            continue
                        try:
                            mount_path, mount_spec, shadow_path, use_cache = parse_mount_request(data)
                            print_info("mount request {}, {}, {}, {}".format(
                                mount_path, mount_spec, shadow_path, use_cache))
                            infinmount.perform_mount(mount_path, mount_spec, shadow_path=shadow_path, use_cache=use_cache)
                            response = "success".encode('utf-8')
                            print_info("mount successful")
                        except Exception as ex:
                            print_info('Exception in mounting: '+str(ex))
                            response = str(ex).encode('utf-8')
                        conn.send(response)
                if not _fetch_upload_pod_status_logs(k8s_client, run_id, pod_name, pod_namespace, int(i/12)):   # i/12 so that we don't create a new log once every 15 seconds
                    print_info("Task process done, exiting mount service")
                    exitCode = get_task_exit_code(k8s_client, pod_name, pod_namespace)
                    if exitCode == 0:
                        update_mlflow_run(run_id, "FINISHED")
                        mlflow_run_status = "FINISHED"
                    else:
                        update_mlflow_run(run_id, "FAILED")
                        mlflow_run_status = "FAILED"
                    _fetch_upload_pod_status_logs(k8s_client, run_id, pod_name, pod_namespace, int(i/12))   # i/12 so that we don't create a new log once every 15 seconds
                    if dag_execution_id:
                        launch_dag_controller()
                    else:
                        print_info('Not a dag execution, skip dag controller')
                    exit(0)
                i+=1
    except Exception as e1:
        if mlflow_run_status:
            print(f"mount_service: Caught {e1}. mlflow_run_status={mlflow_run_status}. Doing nothing", flush=True)
            if mlflow_run_status == "FINISHED":
                exit(0)
            else:
                exit(255)
        else:
            print(f"mount_service: Caught {e1} WARN mlflow_run_status not set. Calling update_mlflow_run for FAILED", flush=True)
            update_mlflow_run(run_id, "FAILED")
            exit(255)
