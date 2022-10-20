from mlflow.tracking import MlflowClient
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument('--run_id', type=str, required=True)
parser.add_argument('--path', type=str, required=True)
parser.add_argument('--dst_path', type=str, required=True)

args = parser.parse_args()

client = MlflowClient()
client.download_artifacts(args.run_id, args.path, args.dst_path)
os._exit(os.EX_OK)