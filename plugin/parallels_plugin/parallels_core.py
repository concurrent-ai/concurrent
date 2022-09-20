import boto3

## Load infin_boto3, even if not used, to decorate boto3
from infinstor import infin_boto3
import tempfile
import mlflow
import os
import json
import pandas as pd
from parallels_plugin.infinfs import infinmount
from urllib.parse import urlparse
import multiprocessing
import glob
import copy
import re
from io import StringIO


def _list_one_dir(client, bucket, prefix_in, arr):
    print("INFO: _list_one_dir: ", bucket, prefix_in)
    paginator = client.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix_in, Delimiter="/")
    for page in page_iterator:
        contents = page.get('Contents')
        if (contents != None):
            # print('   ' + str(contents))
            for one_content in contents:
                if 'Metadata' in one_content:
                    md = json.loads(one_content['Metadata'])
                else:
                    md = {}
                md['FileName'] = one_content['Key']
                md['FileSize'] = one_content['Size']
                md['FileLastModified'] = one_content['LastModified']
                if 'versionId' in one_content:
                    md['FileVersionId'] = one_content['versionId']
                arr.append(md)

        common_prefixes = page.get('CommonPrefixes')
        if (common_prefixes != None):
            for prefix in common_prefixes:
                this_prefix = str(prefix['Prefix'])
                # print('   ' + this_prefix)
                if this_prefix:
                    _list_one_dir(client, bucket, this_prefix, arr)


def _get_artifact_info_from_run(run_info, input_spec=None):
    artifact_uri = run_info.info.artifact_uri
    parse_result = urlparse(artifact_uri)
    if (parse_result.scheme != 's3'):
        raise ValueError('Error. Do not know how to deal with artifacts in scheme ' \
                         + parse_result.scheme)
    bucket = parse_result.netloc
    if input_spec and 'prefix' in input_spec:
        prefix = input_spec['prefix'].lstrip('/').rstrip('/')
    else:
        prefix = os.path.join(parse_result.path.lstrip('/'))
    return bucket, prefix


def _load_input_spec(input_spec):
    if input_spec['type'] == 'infinsnap' or input_spec['type'] == 'infinslice':
        time_spec = input_spec.get('time_spec')
        bucket = input_spec['bucketname']
        prefix = input_spec['prefix']
    elif input_spec['type'] == 'mlflow-run-artifacts':
        client = mlflow.tracking.MlflowClient()
        run = client.get_run(input_spec['run_id'])
        bucket, prefix = _get_artifact_info_from_run(run, input_spec)
        #For mlflow artifacts i.e. intermediate input, request prefix is appended
        time_spec = None
    else:
        bucket = input_spec.get('bucketname')
        prefix = input_spec.get('prefix')
        time_spec = None
    return bucket, prefix, time_spec


def _load_local_csv_metadata(request_path):
    if os.path.isdir(request_path):
        all_files = []
        for root, dirnames, filenames in os.walk(request_path):
            dirnames.sort()
            if filenames:
                for ff in sorted(filenames):
                    all_files.append(os.path.join(root, ff))
    else:
        all_files = [request_path]

    print(all_files)
    data_frames = []
    for f in all_files:
        print('processing file: ', f)
        if f.lower().endswith('.csv'):
            with open(f, "r") as infh:
                df = pd.read_csv(StringIO(infh.read()), sep=",")
                if not df.empty:
                    data_frames.append(df)

    ##Merge all dataframes
    combined_df = pd.concat(data_frames, ignore_index=True)
    return combined_df


def _load_csv_metadata(path, input_name=None):
    ##Override input with runtime inputspec
    input_spec_list = infinmount.get_input_spec_json(input_name=input_name)
    #print("Input specs for metadata: ", input_spec_list)
    if not input_spec_list:
        ##Fallback to default local files
        return _load_local_csv_metadata(path)
    data_frames = []
    all_keys = set()
    storage_spec_list = []
    for input_spec in input_spec_list:
        print("Processing input spec: ", input_spec)
        bucket, prefix, infinstor_time_spec = _load_input_spec(input_spec)
        if infinstor_time_spec:
            client = boto3.client('s3', infinstor_time_spec=infinstor_time_spec)
        else:
            client = boto3.client('s3')
        ##read csv files at the bucket/prefix
        remote_folder = prefix
        paginator = client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=remote_folder, Delimiter="/")
        for page in page_iterator:
            contents = page.get('Contents')
            if contents:
                for one_content in contents:
                    key = one_content['Key']
                    if key.endswith('.csv'):
                        data = client.get_object(Bucket=bucket, Key=key)
                        csv_meta = data['Body'].read()
                        df = pd.read_csv(StringIO(csv_meta), sep=",")
                        if not df.empty:
                            data_frames.append(df)

    ##Merge all dataframes
    combined_df = pd.concat(data_frames, ignore_index=True)
    return combined_df


def __list_local_data_files(request_path):
    all_files = []
    for root, dirnames, filenames in os.walk(request_path):
        dirnames.sort()
        if filenames:
            for ff in sorted(filenames):
                all_files.append(os.path.join(root, ff))
    arr = []
    for f in all_files:
        arr.append({'FileName': f})
    return pd.DataFrame(arr)


def list(path, input_name=None):
    ##Override input with runtime inputspec
    input_spec_list = infinmount.get_input_spec_json(input_name=input_name)
    if not input_spec_list:
        ##Fallback to default local files
        return __list_local_data_files(path)
    data_frames = []
    all_keys = set()
    storage_spec_list = []
    for input_spec in input_spec_list:
        print("Processing input spec: ", input_spec)
        arr = []
        bucket, prefix, infinstor_time_spec = _load_input_spec(input_spec)
        if infinstor_time_spec:
            client = boto3.client('s3', infinstor_time_spec=infinstor_time_spec)
        else:
            client = boto3.client('s3')
        if input_spec['type'] == 'mlflow-run-artifacts':
            metadata_found = _load_mlflow_artifacts_metadata(bucket, prefix, arr)
            if not metadata_found:
                print("No metadata file found, extracting objects")
                _list_one_dir(client, bucket, prefix, arr)
            else:
                print("Loaded metadata file")
        else:
            _list_one_dir(client, bucket, prefix, arr)
        df = pd.DataFrame(arr)
        if df.empty:
            print(f"No data found for input spec {input_spec}... Skipping")
            continue
        keygen_src = None
        if 'partition_keygen' in input_spec:
            keygen_src = input_spec['partition_keygen']
        key_list = _apply_keygen(df, keygen_src)
        all_keys.update(key_list)
        storage_specs = {
            'bucket': bucket,
            'prefix': prefix.strip('/'),
            'input_spec_type': input_spec['type']
        }
        if infinstor_time_spec:
            storage_specs['infinstor_time_spec'] = infinstor_time_spec

        storage_spec_list.append(storage_specs)
        data_frames.append(df)

    if not data_frames:
        print('Warning: no dataframes to process')
        return pd.DataFrame()
    else:
        return _combine_and_filter_dataframes(data_frames, input_spec_list, all_keys, storage_spec_list)


def _combine_and_filter_dataframes(data_frames, input_spec_list, all_keys, storage_spec_list):
    df_to_keep = []
    storage_specs_to_keep = []
    all_keys = sorted(all_keys)
    index = 0
    for df, sspec in zip(data_frames, storage_spec_list):
        df = _filter_df_for_partition(df, input_spec_list[index], all_keys)
        index += 1
        if not df.empty:
            df_to_keep.append(df)
            storage_specs_to_keep.append(sspec)
    row_count = 0
    for df, storage_spec in zip(df_to_keep, storage_specs_to_keep):
        storage_spec['row_start'] = row_count
        storage_spec['num_rows'] = df.shape[0]
        row_count = row_count + df.shape[0]
    if df_to_keep:
        combined_df = pd.concat(df_to_keep, ignore_index=True)
        combined_df.attrs['storage_specs'] = storage_specs_to_keep
        return combined_df
    else:
        return pd.DataFrame()


def _filter_df_for_partition(df, input_spec, all_keys):
    if 'parallelization_schedule' in input_spec:
        psched = input_spec['parallelization_schedule']
        if psched[0] == 'default':
            filtered_df = _default_partitioner_filter(df, all_keys, psched[1], psched[2])
            return filtered_df
    return df


def _perform_mount_for_mount_spec(df, mount_spec, mount_path):
    path_list = df['FileName'].tolist()
    # replace the cloud prefix by mounted path
    cloud_prefix = mount_spec['prefix']
    cloud_prefix_len = len(cloud_prefix) + 1
    local_file_list = []
    for fpath in path_list:
        local_path = os.path.join(mount_path, fpath[cloud_prefix_len:])
        local_file_list.append(local_path)

    infinmount.perform_mount(mount_path, mount_spec)

    return local_file_list


def get_local_paths(df):
    if 'storage_specs' in df.attrs:
        mount_specs = df.attrs['storage_specs']
    else:
        ## Local files
        return df['FileName'].tolist()

    mount_path = tempfile.mkdtemp()

    all_local_files = []
    for i, m_spec in enumerate(mount_specs):
        m_path = os.path.join(mount_path, "part-" + str(i))
        os.mkdir(m_path)
        m_spec['mountpoint'] = m_path
        rb = m_spec['row_start']
        re = rb + m_spec['num_rows']
        local_file_list = _perform_mount_for_mount_spec(df[rb:re], m_spec, m_path)
        all_local_files.extend(local_file_list)
    return all_local_files


def _log_metadata(local_path, artifact_path, **kwargs):
    ##kwargs are treated as metadata.
    print('Emitting output#')
    print(local_path, artifact_path, kwargs)
    metadata = kwargs
    active_run = mlflow.active_run()
    if not active_run and 'MLFLOW_RUN_ID' in os.environ:
        current_run_id = os.environ['MLFLOW_RUN_ID']
        client = mlflow.tracking.MlflowClient()
        active_run = client.get_run(current_run_id)
    if not active_run:
        raise Exception("No mlflow run found in context")
    bucket, prefix = _get_artifact_info_from_run(active_run)
    all_files = glob.iglob(local_path, recursive=True)
    all_metadata = []
    for fpath in all_files:
        md = copy.deepcopy(metadata)
        remote_path = os.path.join(prefix, artifact_path, os.path.basename(fpath))
        md['FileName'] = remote_path
        all_metadata.append(md)

    meta_file_name = artifact_path.replace('/', '__') + "__" + os.path.basename(local_path) + ".json"
    metadata_tmp_local = os.path.join(tempfile.mkdtemp(), meta_file_name)
    os.makedirs(os.path.dirname(metadata_tmp_local), exist_ok=True)
    with open(metadata_tmp_local, "w") as fh:
        json.dump(all_metadata, fh)
    print("Log metadata: ", metadata_tmp_local, ".mlflow-parallels/metadata")
    mlflow.log_artifact(metadata_tmp_local, ".mlflow-parallels/metadata")


def parallels_log_artifact(local_path, artifact_path, **kwargs):
    ##kwargs are treated as metadata.
    _log_metadata(local_path, artifact_path, **kwargs)
    print("Log data output: ", local_path, artifact_path)
    mlflow.log_artifact(local_path, artifact_path)


def parallels_log_artifacts(local_dir, artifact_path, **kwargs):
    ##kwargs are treated as metadata.
    _log_metadata(local_dir, artifact_path, **kwargs)
    print("Log data output: ", local_dir, artifact_path)
    mlflow.log_artifacts(local_dir, artifact_path)


def _load_mlflow_artifacts_metadata(bucket, prefix, arr):
    client = boto3.client('s3')
    remote_folder = os.path.join(prefix, ".mlflow-parallels/metadata/")
    paginator = client.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket, Prefix=remote_folder, Delimiter="/")
    all_metadata = []
    for page in page_iterator:
        contents = page.get('Contents')
        if contents:
            for one_content in contents:
                key = one_content['Key']
                if key.endswith('.json'):
                    data = client.get_object(Bucket=bucket, Key=key)
                    meta_object = data['Body'].read()
                    metadata = json.loads(meta_object.decode("utf-8"))
                    all_metadata = all_metadata + metadata
    arr.extend(all_metadata)
    return bool(all_metadata)


def _default_partitioner_filter(df, all_keys, num_bins, index):
    if not all_keys:
        print("Warning: No filtering applied")
        return df
    key_subset = set()
    for i, key in enumerate(all_keys):
        if i % num_bins == index:
            key_subset.add(key)
    filtered_df = df[df.apply(lambda row: row['partitioning_key'] in key_subset, axis=1)]
    return filtered_df


def _apply_keygen(df, keygen_src):
    print("Keygen function for partitioning:", keygen_src)
    if not keygen_src:
        if 'partitioning_key' in df.columns:
            keygen_func = lambda row : row['partitioning_key']
        else:
            ##By default we use object partitioning
            keygen_func = lambda row: row['FileName']
    elif keygen_src == 'directory':
        keygen_func = lambda row : os.path.basename(os.path.dirname(row['FileName']))
    elif keygen_src == 'custom':
        keygen_func = eval(keygen_src)
    elif keygen_src == 'object':
        keygen_func = lambda row: row['FileName']
    elif keygen_src == 'broadcast':
        ##No partitioning, same data is partitioned for all parallel instances
        return []
    else:
        keygen_func = eval(keygen_src)
    keydf = pd.DataFrame([])
    keydf['partitioning_key'] = df.apply(lambda row: keygen_func(row), axis = 1)
    df['partitioning_key'] = keydf['partitioning_key']
    return sorted(keydf['partitioning_key'].unique())





