import argparse
import sys
import os
from concurrent_plugin.login import get_conf, get_token, get_token_file_obj, get_env_var
from requests.exceptions import HTTPError
import requests
import json

parser = argparse.ArgumentParser(epilog='Example: python -m concurrent_plugin.periodic_run add --periodic_run_name test1 --schedule "06_22_*_*_*_*" --schedule_type once --dagid DAG1665114786385 --experiment_id 7')
parser.add_argument('operation', type=str, choices=['add', 'delete', 'list'])
parser.add_argument('--periodic_run_name', type=str, required=False)
parser.add_argument('--schedule', type=str, required=False, help='format is a_b_c_d_e_f where a=minutes(0-59), b=hour(0-23), c=day_of_month(1-31), d=month(1-12), e=day_of_week(0-7, 0 is Sunday)')
parser.add_argument('--schedule_type', type=str, required=False, choices=['once', 'hourly', 'daily', 'weekly', 'monthly', 'yearly'])
parser.add_argument('--experiment_id', type=int, required=False)
parser.add_argument('--dagid', type=str, required=False)

args = parser.parse_args()

if args.operation == 'add' and (not args.schedule or not args.schedule_type or not args.experiment_id or not args.dagid):
    print('Error. schedule, schedule_type, experiment_id and dagid are required for the add operation', flush=True)
    parser.print_help()
    sys.exit(255)

if args.operation != 'list' and not args.periodic_run_name:
    print('Error. periodic_run_name is required for ' + args.operation, flush=True)
    parser.print_help()
    sys.exit(255)

cognito_client_id, _, _, _, region = get_conf()
token = get_token(cognito_client_id, region, True)

headers = {
        'Content-Type': 'application/x-amz-json-1.1',
        'Authorization' : 'Bearer ' + token
        }

if args.operation == 'add':
    pr = {
        'period': {'type': args.schedule_type, 'value': args.schedule},
        'experiment_id': args.experiment_id,
        'dagid': args.dagid,
        'MLFLOW_TRACKING_URI': os.getenv('MLFLOW_TRACKING_URI'),
        'MLFLOW_CONCURRENT_URI': os.getenv('MLFLOW_CONCURRENT_URI')
    }
    mtt = os.getenv('MLFLOW_TRACKING_TOKEN')
    if mtt:
        pr['MLFLOW_TRACKING_TOKEN'] = mtt
    url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/add-mod-periodicrun'
    try:
        response = requests.post(url,
                data={'periodicRunName': args.periodic_run_name, 'periodicRunJson': json.dumps(pr)},
                headers=headers)
        response.raise_for_status()
    except HTTPError as http_err:
        print(f'HTTP error occurred: {http_err}', flush=True)
        raise
    except Exception as err:
        print(f'Other error occurred: {err}', flush=True)
        raise
    else:
        sys.exit(0)
elif args.operation == 'delete':
    url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/del-periodicrun'
    try:
        response = requests.post(url, data={'periodicRuns': args.periodic_run_name}, headers=headers)
        response.raise_for_status()
    except HTTPError as http_err:
        print(f'HTTP error occurred: {http_err}', flush=True)
        raise
    except Exception as err:
        print(f'Other error occurred: {err}', flush=True)
        raise
    else:
        sys.exit(0)
elif args.operation == 'list':
    url = get_env_var().rstrip('/') + '/api/2.0/mlflow/parallels/list-periodicruns'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except HTTPError as http_err:
        print(f'HTTP error occurred: {http_err}', flush=True)
        raise
    except Exception as err:
        print(f'Other error occurred: {err}', flush=True)
        raise
    else:
        rsp = json.loads(response.text)
        prs = rsp['periodicRuns']
        for pr in prs:
            print(str(pr['name']) + ': type=' + str(pr['type'])
                    + ', period=' + str(pr['period']) + ', dagid=' + str(pr['dagid'])
                    + ', experiment_id=' + str(pr['experiment_id']), flush=True)
        sys.exit(0)
sys.exit(255)
