import os
import boto3
from infinstor import infin_boto3


def get_s3_client(infinstor_time_spec):
    if infinstor_time_spec:
        return boto3.client('s3', infinstor_time_spec=infinstor_time_spec)
    else:
        return boto3.client('s3')

def download_objects(local_path, tmp_local_file, bucket, remote_path, infinstor_time_spec, client = None):
    print("Download from bucket {0}, path {1} to the local path {2} for timespec {3}"
             .format(bucket, remote_path, tmp_local_file, str(infinstor_time_spec)))
    download_one_object(tmp_local_file, bucket, remote_path, infinstor_time_spec, client)
    print('rename {0} to {1}'.format(tmp_local_file, local_path))
    os.rename(tmp_local_file, local_path)

def download_one_object(local_path, bucket, remote_path, infinstor_time_spec, client = None):
    if client:
        s3_client = client
    else:
        s3_client = get_s3_client(infinstor_time_spec)
    s3_client.download_file(bucket, remote_path, local_path)




