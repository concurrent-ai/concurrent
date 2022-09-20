from mlflow.tracking import MlflowClient
import infinstor_mlflow_plugin
import boto3
import argparse
import os
import json

parser = argparse.ArgumentParser()
parser.add_argument('--run_id', type=str, required=True)
parser.add_argument('--path', type=str, required=True)
parser.add_argument('--file_name', type=str, required=True)

args = parser.parse_args()

client = MlflowClient()
client.log_artifact(args.run_id, args.file_name)
os._exit(os.EX_OK)
