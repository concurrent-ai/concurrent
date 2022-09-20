from mlflow.tracking import MlflowClient
import infinstor_mlflow_plugin
import boto3
import argparse
import os
import json
from mlflow.utils.mlflow_tags import (
        MLFLOW_RUN_NAME,
        MLFLOW_SOURCE_NAME,
        MLFLOW_SOURCE_TYPE,
        MLFLOW_PARENT_RUN_ID,
)

parser = argparse.ArgumentParser()
parser.add_argument('--experiment_id', type=int, required=True)
parser.add_argument('--run_name', type=str, required=False)
parser.add_argument('--parent_run_id', type=str, required=False)
parser.add_argument('--source_name', type=str, required=False)
parser.add_argument('--tags', type=str, required=False)

args = parser.parse_args()

tags = {}
if args.run_name:
    tags[MLFLOW_RUN_NAME] = args.run_name
if args.parent_run_id:
    tags[MLFLOW_PARENT_RUN_ID] = args.parent_run_id
    tags[MLFLOW_SOURCE_TYPE] = 'PROJECT'
if args.source_name:
    tags[MLFLOW_SOURCE_NAME] = args.source_name

if args.tags:
    additional_tags = json.loads(args.tags)
    for k, v in additional_tags.items():
        tags[k] = v

client = MlflowClient()
run = client.create_run(str(args.experiment_id), tags=tags)

print(json.dumps({'run_id': str(run.info.run_uuid),
            'artifact_uri': str(run.info.artifact_uri),
            'status': str(run.info.status),
            'lifecycle_stage': str(run.info.lifecycle_stage)}), flush=True)
os._exit(os.EX_OK)
