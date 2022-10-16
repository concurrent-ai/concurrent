import json
import sys
import os
import io
import logging
import time
from datetime import datetime, timezone
import re
from os.path import sep
import tempfile
import sysconfig

import boto3
import requests
from requests.exceptions import HTTPError

from utils import get_service_conf, create_request_context
from periodic_run_utils import get_periodic_run_info
from transform_utils import get_xform_info, make_short_name

import dag_utils, execute_dag

from urllib.parse import urlparse
from mlflow_utils import call_create_run
import run_project 

logger = logging.getLogger()
logger.setLevel(logging.INFO)

verbose = True

def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': str(err) if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*',
            'Access-Control-Allow-Credentials': '*'
        },
    }


def period_run(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    item = event
    periodic_run_id = item['periodic_run_id']
    logger.info('periodic_run_id=' + str(periodic_run_id))
    username = item['username']
    customCustomerId = item['customCustomerId']
    logger.info('username=' + str(username))
    logger.info('customCustomerId=' + str(customCustomerId))
    cognito_username = username

    success, status, periodic_run = get_periodic_run_info(cognito_username, periodic_run_id)

    if (success == False):
        logger.error("No periodic run found for id "+str(periodic_run_id))
        return respond(ValueError('Could not find periodic run '
                                  + periodic_run_id + ', err=' + status))
    periodic_run_name = periodic_run['periodic_run_name']

    success, status, service_conf = get_service_conf()
    if (success == False):
        err = 'period_run: Error {0} lookup service conf'.format(status)
        logger.error(err)
        return respond(ValueError(err))

    logger.info(periodic_run)
    periodic_run_info = json.loads(periodic_run['json']['S'])

    frequency = periodic_run_info.get('period').get('type')
    experiment_id = periodic_run_info['experiment_id']
    cognito_client_id = service_conf['cognitoClientId']['S']
    custom_token = None
    if 'custom_token' in periodic_run:
        custom_token = periodic_run['custom_token']['S']
    auth_info = {
            'mlflow_tracking_uri' : periodic_run_info.get('MLFLOW_TRACKING_URI'),
            'mlflow_tracking_token': periodic_run_info.get('MLFLOW_TRACKING_TOKEN'),
            'mlflow_concurrent_uri': periodic_run_info.get('MLFLOW_CONCURRENT_URI'),
            'custom_token': custom_token,
            'cognito_client_id': cognito_client_id
            }

    if not 'dagid' in periodic_run_info:
        logger.error("dagid required for period runs")
        return respond(ValueError('Could not find dagid for run ' + periodic_run_id))
    if 'data' in periodic_run_info:
        data = periodic_run_info['data']
    else:
        data = None
    print("Periodic execution of dag for dagid " + periodic_run_info['dagid'])
    launch_dag(cognito_username, periodic_run_name, periodic_run_info['dagid'], experiment_id,
                auth_info, frequency, data)
    return

def launch_dag(cognito_username, periodic_run_name, dagid, experiment_id, auth_info,
        frequency, data):
    print('periodic dag execution')
    dag_json = dag_utils.fetch_dag_details(cognito_username, dagid)

    #dag may already have an experiment id but for periodic run,
    #we use the experiment id assigned to the periodic run
    dag_json['experiment_id'] = experiment_id

    dag_execution_id = dag_utils.get_new_dag_exec_id(dagid)
    # create parent run
    parent_run_name = dag_json['name'] + "-" + periodic_run_name
    parent_run_id, parent_artifact_uri, parent_run_status, parent_run_lifecycle_stage \
        = call_create_run(cognito_username, experiment_id, auth_info, parent_run_name)

    dag_execution_status = {'parent_run_name': parent_run_name, 'parent_run_id': parent_run_id}
    node_statuses = dict()
    for n in dag_json['nodes']:
        node_statuses[n['id']] = {'status': 'PENDING'}
        for node_input in n['input']:
            input_type = node_input['type'].lower()
            if input_type == 'infinsnap' or input_type == 'infinslice':
                if not data:
                    input_data = {'type': input_type, 'bucket': node_input['bucketname'],
                                  'path_in_bucket': get_path_prefix(node_input)}
                else:
                    ##TODO: get bucket and input for each node
                    input_data = data
                input_spec_object = get_input_data_spec_object(input_data, frequency)
                node_input['time_spec'] =  input_spec_object['time_spec']
                print('Updated Spec: ', node_input)
    dag_execution_status['nodes'] = node_statuses
    dag_utils.create_dag_execution_record(cognito_username, dagid, dag_execution_id, dag_execution_status, dag_json)

    #Invoke execute_dag
    dag_event = dict()
    dag_event['username'] = cognito_username
    dag_event['dagid'] = dagid
    dag_event['dag_execution_id'] = dag_execution_id
    dag_event['periodic_run_name'] = periodic_run_name
    dag_event['experiment_id'] = experiment_id
    dag_event['frequency'] = frequency
    return execute_dag.execute_dag(dag_event, None)


def get_path_prefix(node_input):
    if 'pathInBucket' in node_input:
        return node_input['pathInBucket']
    elif 'prefix' in node_input:
        return node_input['prefix']
    else:
        raise('No prefix specified')


def get_input_data_spec_object(data, frequency):
    input_data_spec = dict()
    input_data_spec['type'] = data['type']
    input_data_spec['bucketname'] = data['bucket']
    # the 'prefix' should not start with a '/' to avoid a double slash in the output artifact object key in s3, like 's3://bucketname/.../infinstor//logs/stdout-stderr.txt'.  
    # Note that, code injected by Run > Transform does not have a leading '/' for the 'prefix' in input_data_spec={prefix: xxxxx}
    # also the code infinstor/__init__.py::get_mlflow_run_artifacts_info(), which generates the 'prefix' in input_data_spec={prefix: xxxxx}, for mlflow run artifacts as input, does a lstrip('/') on the path 
    input_data_spec['prefix'] = data['path_in_bucket'].lstrip('/')  
    ts, formatted_ts = get_current_timestamp()
    if data['type'] == 'infinsnap':
        infin_timestamp = "tm{0}".format(formatted_ts)
    elif data['type'] == 'infinslice':
        last_run_ts = get_last_run_timestamp(ts, frequency, data.get('slice'))
        infin_timestamp = "tm{0}-tm{1}".format(last_run_ts, formatted_ts)
    else:
        raise Exception("Invalid type of data source specified")
    input_data_spec['time_spec'] = infin_timestamp

    logger.info('input_data_spec#')
    logger.info(input_data_spec)
    return input_data_spec

def get_current_timestamp():
    ts = time.time()
    return ts, datetime.fromtimestamp(ts).strftime('%Y%m%d%H%M%S')

def get_last_run_timestamp(ts, frequency, slice=None):
    if (frequency == 'hourly'):
        last_period_ts = ts - 60*60
    elif (frequency == 'daily'):
        last_period_ts = ts - 24 * 60 * 60
    elif (frequency == 'weekly'):
        last_period_ts = ts - 7*24*60*60
    elif (frequency == 'monthly'):
        dt = datetime.fromtimestamp(ts)
        if (dt.month == 1):
            newDt = dt.replace(month=12, year=dt.year - 1)
        else:
            newDt = dt.replace(month=dt.month - 1)
        last_period_ts = newDt.timestamp()
    elif (frequency == 'yearly'):
        dt = datetime.fromtimestamp(ts)
        last_period_ts = dt.replace(year=dt.year - 1).timestamp()
    elif (frequency == 'once'):
        print("Last run doesn't make sense for frequency 'once'")
        raise Exception("Last run doesn't make sense for frequency 'once'")
    else:
        raise Exception("Invalid frequency: "+frequency)

    if slice:
        print('slice = '+str(slice) + '%')
        last_ts = ts - int (((ts - last_period_ts) * slice) / 100)
    else:
        last_ts = last_period_ts

    return datetime.fromtimestamp(last_ts).strftime('%Y%m%d%H%M%S')

# Test
if __name__ == "__main__":
    event = dict()
    event['httpMethod'] = 'POST'
    claims = {'principalId' : 'isstage5'}
    claims['aud'] = "unknown"
    request_context = {'authorizer': claims}
    event['requestContext'] = request_context
    event['body'] = json.dumps({'periodic_run_id' : 'titanic_weekly'})
    period_run(event, "")
