from mlflow.tracking import MlflowClient
import infinstor_mlflow_plugin
import boto3
import argparse
import os
import json

parser = argparse.ArgumentParser()
parser.add_argument('--run_id', type=str, required=True)

args = parser.parse_args()

client = MlflowClient()
run = client.get_run(str(args.run_id))

run_info = {
    'run_id': str(run.info.run_uuid),
    'artifact_uri': str(run.info.artifact_uri),
    'status': str(run.info.status),
    'lifecycle_stage': str(run.info.lifecycle_stage)
}
if run.data.params:
    run_info['params'] = run.data.params

print(json.dumps(run_info), flush=True)
os._exit(os.EX_OK)
