import sys
import os
from fuse import FUSE, fuse_exit
import subprocess
import time
import mlflow
import glob
import json
from urllib.parse import urlparse

import infinstor
from infinstor.infinfs.infinfs import InfinFS

INPUT_SPEC_CONFIG = '/root/.mlflow-parallels-data/inputdataspec'

fuse_debug_handle = None
fuse_debug_file = "/tmp/fuse_debug.log"
fuse_debug_handle = open(fuse_debug_file, "a")

def launch_fuse_infinfs(ifs):
    mountpath = ifs.get_mountpoint()
    if os.path.ismount(mountpath):
        umountp = subprocess.Popen(['umount', '-lf', mountpath], stdout=sys.stdout, stderr=subprocess.STDOUT)
        umountp.wait()
    FUSE(ifs, mountpath, nothreads=True, foreground=False)
    print("exiting")


def get_input_spec_json(input_name=None):
    config_path = INPUT_SPEC_CONFIG
    if 'MLFLOW_RUN_ID' in os.environ:
        config_path = config_path + "-" + os.environ['MLFLOW_RUN_ID']
    print("Input spec config path:", config_path)
    if not os.path.isfile(config_path):
        print(config_path + ' does not exist. Load local paths')
        return None
    with open(config_path, 'r', encoding="utf-8") as fp:
        inp_contents = fp.read()
    specs = json.loads(inp_contents)
    print("Input specs for input_name ", input_name, ": ", specs)
    named_spec_map = get_named_input_spec_map(specs)
    if input_name:
        specs = named_spec_map.get(input_name)
    return specs


def perform_mount(mountpoint_path, mount_spec_object):
    mounted_paths_list = []
    mounted_paths_list.append(mountpoint_path)
    mount_spec_str = json.dumps(mount_spec_object)
    fuse_process = subprocess.Popen(['python', os.path.realpath(__file__), mount_spec_str],
                                    stdout=fuse_debug_handle, stderr=subprocess.STDOUT)

    ##Check if mounts are visible
    max_wait_time = 300
    for mp in mounted_paths_list:
        print("Waiting for mountpoint {0} to be visible".format(mp))
        while not os.path.ismount(mp):
            sleep_time = 3
            time.sleep(sleep_time)
            if max_wait_time <= 0:
                raise Exception('Failed to mount')
            else:
                max_wait_time = max_wait_time - sleep_time
        print("{0} mounted successfully".format(mp))


def infin_log_output(output_dir):
    if 'INFINSTOR_SERVICE' not in os.environ:
        print("No action needed")
        return
    if mlflow.active_run():
        infinstor.log_all_artifacts_in_dir(None, None, output_dir, delete_output=False)
    else:
        print('No active run')

def get_named_input_spec_map(inputs):
    named_map = dict()
    for item in inputs:
        name = item['name']
        if name not in named_map:
            named_map[name] = []
        named_map[name].append(item)
    return named_map


def get_partition_mount_prefix(mount_spec_object, unsplitted_prefix, partition_prefix, requested_mountpoint):
    print("get_partition_mount_prefix ##")
    print(unsplitted_prefix, partition_prefix, requested_mountpoint)
    original_prefix = unsplitted_prefix.lstrip("/").rstrip("/")
    partition_prefix = partition_prefix.lstrip("/").rstrip("/")
    if original_prefix == partition_prefix:
        print('Partitioned prefix is same as unsplitted prefix')
        mount_spec_object['prefix'] = partition_prefix
        mount_spec_object['mountpoint'] = requested_mountpoint
    elif not original_prefix:
        print("Original prefix is empty")
        mount_spec_object['prefix'] = partition_prefix
        mount_spec_object['mountpoint'] = os.path.join(requested_mountpoint, partition_prefix)
        os.makedirs(mount_spec_object['mountpoint'], exist_ok=True)
    elif partition_prefix.startswith(original_prefix):
        print("Extending prefix for partitioning")
        part = partition_prefix[len(original_prefix):].lstrip('/')
        mount_spec_object['mountpoint'] = os.path.join(requested_mountpoint, part)
        os.makedirs(mount_spec_object['mountpoint'], exist_ok=True)
        mount_spec_object['prefix'] = partition_prefix
    else:
        raise Exception('Invalid partition prefix ')


def load_input_specs(specs, requested_mountpoint):
    print('specs ##')
    print(specs)
    mount_spec_object = dict()
    mount_spec_object['mountpoint'] = requested_mountpoint
    if specs['type'] == 'infinsnap' or specs['type'] == 'infinslice':
        time_spec = specs.get('time_spec')
        bucket = specs['bucketname']
        prefix = specs['prefix']
        if time_spec:
            mount_spec_object['infinstor_time_spec'] = time_spec
        mount_spec_object['bucket'] = bucket
        if 'unsplitted_prefix' in specs:
            get_partition_mount_prefix(mount_spec_object, specs['unsplitted_prefix'], prefix, requested_mountpoint)
        else:
            mount_spec_object['prefix'] = prefix.lstrip('/').rstrip('/')
    elif specs['type'] == 'mlflow-run-artifacts':
        client = mlflow.tracking.MlflowClient()
        run = client.get_run(specs['run_id'])
        artifact_uri = run.info.artifact_uri
        parse_result = urlparse(artifact_uri)
        if (parse_result.scheme != 's3'):
            raise ValueError('Error. Do not know how to deal with artifacts in scheme ' \
                             + parse_result.scheme)
        mount_spec_object['bucket'] = parse_result.netloc
        if 'unsplitted_prefix' in specs and 'prefix' in specs:
            get_partition_mount_prefix(mount_spec_object, specs['unsplitted_prefix'], specs['prefix'],
                                       requested_mountpoint)
        elif 'prefix' in specs:
            mount_spec_object['prefix'] = specs['prefix'].lstrip('/').rstrip('/')
        else:
            mount_spec_object['prefix'] = os.path.join(parse_result.path.lstrip('/'), "infinstor")
    ##Ensure mountpoint dir exists
    os.makedirs(mount_spec_object['mountpoint'], exist_ok=True)
    return mount_spec_object


if __name__ == '__main__':
    mount_spec_str = sys.argv[1]
    mount_specs = json.loads(mount_spec_str)

    if mount_specs == None:
        print('Error no input spec found, skipping mount')
        exit(-1)

    service_name = os.environ.get('INFINSTOR_SERVICE')
    ifs = InfinFS(mount_specs)
    launch_fuse_infinfs(ifs)
    exit(0)
