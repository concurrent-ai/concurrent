import sys
import os
import asyncio
import boto3
import time

def get_s3_client():
    return boto3.client('s3')

async def download_one_object(local_path, bucket, remote_path, tmp_location):
    s3_client = get_s3_client()
    local_tmp_path = tmp_location + "/" + os.path.basename(local_path)
    s3_client.download_file(bucket, remote_path, local_tmp_path)
    os.rename(local_tmp_path, local_path)

async def download_batch(batchfile, tmp_location):
    fh = open(batchfile, "r")
    all_lines = fh.readlines()
    taskList = []
    for line in all_lines:
        local_path, bucket, remote_path = line.split(' ')
        t = asyncio.create_task(download_one_object(local_path, bucket, remote_path, tmp_location))
        taskList.append(t)

    for t in taskList:
        await t


def prefetch(local_cache_metadata):
    batch_localtion = local_cache_metadata +"/batches"
    tmp_location = local_cache_metadata +"/tmp"
    while (True):
        batchlist = os.listdir(batch_localtion)
        if batchlist:
            for batchfile in batchlist:
                asyncio.run(download_batch(batchfile, tmp_location))
                done_location = local_cache_metadata +"/done_batches"
                os.rename(batchfile, done_location)
        else:
            print("Done")


if __name__ == '__main__':
    prefetch(sys.argv[1])