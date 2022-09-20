from mlflow.tracking import MlflowClient
import infinstor_mlflow_plugin
import boto3
import argparse
import os
import json

parser = argparse.ArgumentParser()
parser.add_argument('--experiment_name', type=str, required=True)

args = parser.parse_args()

client = MlflowClient()
experiment_id = client.create_experiment(str(args.experiment_name))

print(json.dumps({'experiment_id': str(experiment_id)}), flush=True)
os._exit(os.EX_OK)
