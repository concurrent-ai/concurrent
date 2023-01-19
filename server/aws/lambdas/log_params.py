from mlflow.tracking import MlflowClient
import argparse
import os
import json

parser = argparse.ArgumentParser()
parser.add_argument('--run_id', type=str, required=True)
parser.add_argument('--params', type=str, required=True)

args = parser.parse_args()
params = json.loads(args.params)
run_id = args.run_id
print("Logging params: ", params, "run_id: ", run_id)
client = MlflowClient()
for pkey, pval in params.items():
    client.log_param(run_id, pkey, str(pval))
os._exit(os.EX_OK)