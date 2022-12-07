import socket
import time
import os
from concurrent_plugin.infinfs import infinmount
import json
from mlflow.tracking import MlflowClient
import psutil
from concurrent_plugin.concurrent_backend import MOUNT_SERVICE_READY_MARKER_FILE

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

if __name__ == '__main__':
    print_info("Starting..")
    HOST = "127.0.0.1"
    PORT = 7963
    last_upload_time = time.time()

    start_time = time.time()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.bind((HOST, PORT))
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
                    continue
                else:
                    print_info("Task process done, exiting mount service")
                    exit(0)








