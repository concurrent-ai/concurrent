from mlflow.tracking import MlflowClient
import infinstor_mlflow_plugin
import boto3
import argparse
import os
import json

parser = argparse.ArgumentParser()
parser.add_argument('--run_id', type=str, required=True)
parser.add_argument('--state', type=str, required=True)

args = parser.parse_args()

client = MlflowClient()
run = client.set_terminated(str(args.run_id), status=str(args.state))
os._exit(os.EX_OK)
