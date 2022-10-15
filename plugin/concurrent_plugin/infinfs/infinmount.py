import os
import subprocess
import time
import mlflow
import json
from urllib.parse import urlparse


INPUT_SPEC_CONFIG = '/root/.concurrent-data/inputdataspec'

VERBOSE = True

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


def perform_mount(mountpoint_path, mount_spec_object, use_cache=True, shadow_path=None):
    mounted_paths_list = []
    mounted_paths_list.append(mountpoint_path)
    mount_spec_str = json.dumps(mount_spec_object)

    if VERBOSE:
        cmd = ['python', '-u', '-m', 'concurrent_plugin.infinfs.mount_main', mount_spec_str]
    else:
        cmd = ['python', '-m', 'concurrent_plugin.infinfs.mount_main', mount_spec_str]

    if use_cache:
        cmd.append('True')
    else:
        cmd.append('False')
    if shadow_path:
        cmd.append(shadow_path)
    fuse_process = subprocess.Popen(cmd, stderr=subprocess.STDOUT)

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

