import socket
import time
import os
import traceback
from typing import Any, Union
from concurrent_plugin.infinfs import infinmount
import json
import yaml
from mlflow.tracking import MlflowClient
import psutil
from concurrent_plugin.concurrent_backend import MOUNT_SERVICE_READY_MARKER_FILE
import logging
import requests
import subprocess
# importing it as kubernetes.client since 'client' is used in the code in some places as the Mlflow client.  this mlflow 'client' conflicts with 'from kubernetes import client'.  Need to cleanup.
import kubernetes.client
from kubernetes import client, config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


FUSE_DEBUG_FILE = '/tmp/fuse_debug.log'
VERBOSE = False

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


def check_pid(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


##Returns true if any task is active
def check_pids():
    task_processes = []
    for proc in psutil.process_iter():
        pid = proc.pid
        with open('/proc/' + str(pid) + '/cmdline') as inf:
            cmdline = inf.read()
            if 'mount_main' in cmdline or 'mount_service' in cmdline:
                continue
            if 'python' in cmdline:
                task_processes.append(pid)

    if not task_processes:
        return False

    some_tasks_active = False
    for pid in task_processes:
        alive = check_pid(pid)
        if alive:
            some_tasks_active = True
            break
    return some_tasks_active


def print_info(*args):
    print(*args)


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
        pod_logs = k8s_client.read_namespaced_pod_log(pod_name, pod_namespace, container=container_name)
        with open(tmp_log_file, "w") as fh:
            fh.write(pod_logs)
    except Exception as ex:
        logger.warning("Failed to fetch logs for {}, {}: {}".format(run_id, pod_name, ex))
        return

    try:
        client = MlflowClient()
        client.log_artifact(run_id, tmp_log_file, artifact_path='.concurrent/logs')
    except Exception as ex:
        logger.warning("Failed upload logs for {}, {}: {}".format(run_id, pod_name, ex))


def update_mlflow_run(run_id, status):
    client = MlflowClient()
    client.set_terminated(run_id, status)

def _filter_empty_in_dict_list_scalar(dict_list_scalar:Union[list, dict, Any]):
    try:
        # depth first traveral
        if isinstance(dict_list_scalar, dict):
            keys_to_del:list = []
            for k in dict_list_scalar.keys():  
                _filter_empty_in_dict_list_scalar(dict_list_scalar[k])
                
                # check if the 'key' is now None or empty.  If so, remove the 'key'
                if not dict_list_scalar[k]: 
                    # RuntimeError: dictionary changed size during iteration
                    # dict_list_scalar.pop(k)
                    keys_to_del.append(k)
            
            # now delete the keys from the map
            for k in keys_to_del:
                dict_list_scalar.pop(k)
        elif isinstance(dict_list_scalar, list):
            i = 0; length = len(dict_list_scalar)
            while i < length: 
                _filter_empty_in_dict_list_scalar(dict_list_scalar[i])
            
                # check if element is now None or empty.  If so, remove the element from the list
                if not dict_list_scalar[i]:
                    dict_list_scalar.remove(dict_list_scalar[i])
                    i -= 1; length -= 1
                
                i += 1
        else: # must be a non container like int, str, datatime.datetime
            pass
    except Exception as e:
        # some excpetion, just log it..
        print(f"_filter_empty_in_dict_list_scalar(): Caught exception: {e}")
        traceback.print_exc()

def log_describe_pod(k8s_client:kubernetes.client.CoreV1Api, run_id, pod_name, pod_namespace, pod_info:kubernetes.client.V1Pod):
    describe_file = "/tmp/describe-" + pod_name + ".txt"
    try:
        events:kubernetes.client.V1EventList = k8s_client.list_namespaced_event(pod_namespace, field_selector=f'involvedObject.name={pod_name}')
        with open(describe_file, "w") as fh:
            pod_info_dict:dict = pod_info.to_dict()
            # remove metadata/managed_fields key
            pod_info_dict['metadata'].pop('managed_fields')            
            _filter_empty_in_dict_list_scalar(pod_info_dict)
            fh.write(yaml.safe_dump(pod_info_dict))
            
            events_dict:dict = events.to_dict()
            # remove metadata/managed_fields key
            events_dict['metadata'].pop('managed_fields')            
            _filter_empty_in_dict_list_scalar(events_dict)
            fh.write(yaml.safe_dump(events_dict))
        client = MlflowClient()
        client.log_artifact(run_id, describe_file, artifact_path='.concurrent/logs')
    except Exception as ex:
        logger.warning('Failed to log describe pod, try again later: ' + str(ex))
        return

def fetch_upload_pod_status_logs(k8s_client:client.CoreV1Api, run_id, pod_name, pod_namespace):
    pod_info:client.V1Pod = k8s_client.read_namespaced_pod(pod_name, pod_namespace)
    pod_phase = pod_info.status.phase
    print("pod_phase: ", pod_phase)
    if pod_info.spec.containers[1].name.startswith('sidecar-'):
        side_car_container_name = pod_info.spec.containers[1].name
        task_container_name = pod_info.spec.containers[0].name
    else:
        task_container_name = pod_info.spec.containers[1].name
        side_car_container_name = pod_info.spec.containers[0].name
    if pod_phase:
        if pod_phase == 'Pending':
            logger.info("{} is in Pending phase. Waiting".format(pod_name))
            log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/run-logs.txt",
                                container_name=task_container_name)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, f"/tmp/sidecar-logs.txt",
                                container_name=side_car_container_name)
        elif pod_phase == 'Running':
            logger.info("{} is in Running phase. Waiting".format(pod_name))
            log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/run-logs.txt",
                                container_name=task_container_name)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/sidecar-logs.txt",
                                container_name=side_car_container_name)
        elif pod_phase == 'Succeeded':
            logger.info("{} is in Succeeded phase".format(pod_name))
            log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/run-logs.txt",
                                container_name=task_container_name)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/sidecar-logs.txt",
                                container_name=side_car_container_name)
        elif pod_phase == 'Failed':
            logger.info("{} is in Failed phase".format(pod_name))
            log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/run-logs.txt",
                                container_name=task_container_name)
            upload_logs_for_pod(k8s_client, run_id, pod_name, pod_namespace, "/tmp/sidecar-logs.txt",
                                container_name=side_car_container_name)
        elif pod_phase == 'Unknown':
            logger.warning("{} is in Unknown phase".format(pod_name))
            log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
        else:
            logger.warning("{} is in unfamiliar phase {}".format(pod_name, pod_phase))
            log_describe_pod(k8s_client, run_id, pod_name, pod_namespace, pod_info)
    else:
        return


def get_task_exit_code(k8s_client, pod_name, pod_namespace, num_attempt=1):
    max_attempts = 3
    pod_info = k8s_client.read_namespaced_pod(pod_name, pod_namespace)
    try:
        if pod_info.spec.containers[1].name.startswith('sidecar-'):
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
    print("Environment #", os.environ)
    config.load_incluster_config()
    k8s_client:client.CoreV1Api = client.CoreV1Api()
    run_id = os.getenv('MLFLOW_RUN_ID')
    pod_name = os.getenv('MY_POD_NAME')
    pod_namespace = os.getenv('MY_POD_NAMESPACE')
    dag_execution_id = os.getenv('DAG_EXECUTION_ID')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.bind((HOST, PORT))
        print('Mount/Monitor service starting for runid {0}, and podname {1}'.format(run_id, pod_name))
        print('Listening on port {}:{}'.format(HOST, PORT))
        s.listen()
        mount_service_ready()
        while True:
            print_info('Waiting for request..')
            try:
                conn, addr = s.accept()
            except socket.timeout:
                pass
            else:
                with conn:
                    print(f"Connected by {addr}")
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
            ##Check if tasks are alive
            curr_time = time.time()
            if curr_time - start_time > 30:
                tasks_alive = check_pids()
                if tasks_alive:
                    if last_upload_time + 30 < curr_time:
                        fetch_upload_pod_status_logs(k8s_client, run_id, pod_name, pod_namespace)
                        last_upload_time = curr_time
                else:
                    print_info("Task process done, exiting mount service")
                    exitCode = get_task_exit_code(k8s_client, pod_name, pod_namespace)
                    if exitCode == 0:
                        update_mlflow_run(run_id, "FINISHED")
                    else:
                        update_mlflow_run(run_id, "FAILED")
                    fetch_upload_pod_status_logs(k8s_client, run_id, pod_name, pod_namespace)
                    if dag_execution_id:
                        launch_dag_controller()
                    else:
                        logger.info('Not a dag execution, skip dag controller')
                    exit(0)

