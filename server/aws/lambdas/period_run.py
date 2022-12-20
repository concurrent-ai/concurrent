import json
import sys
import os
import io
import logging
import time
from datetime import datetime, timezone, timedelta
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

    success, status, service_conf = get_service_conf()
    if (success == False):
        err = 'period_run: Error {0} lookup service conf'.format(status)
        logger.error(err)
        return respond(ValueError(err))

    logger.info(periodic_run)
    periodic_run_info = json.loads(periodic_run['json']['S'])
    if not 'dagid' in periodic_run_info:
        logger.error("dagid required for period runs")
        return respond(ValueError('Could not find dagid for run ' + periodic_run_id))

    cognito_client_id = service_conf['cognitoClientId']['S']
    dag_event = dict()
    dag_event['username'] = cognito_username
    dag_event['dagid'] = periodic_run_info['dagid']
    dag_event['periodic_run_name'] = periodic_run['periodic_run_name']
    dag_event['experiment_id'] = str(periodic_run_info['experiment_id'])
    dag_event['frequency'] = periodic_run_info.get('period').get('type')
    dag_event['periodic_run_start_time'] = time.time_ns()//1_000_000
    dag_event['MLFLOW_TRACKING_URI'] = periodic_run_info.get('MLFLOW_TRACKING_URI')
    dag_event['MLFLOW_TRACKING_TOKEN'] = periodic_run_info.get('MLFLOW_TRACKING_TOKEN')
    dag_event['MLFLOW_CONCURRENT_URI'] = periodic_run_info.get('MLFLOW_CONCURRENT_URI')

    period_type = periodic_run_info['period']['type']
    if period_type != 'once':
        munged_dag = munge_input_data(cognito_username, dag_event['dagid'], period_type)
        if munged_dag:
            dag_event['dagParamsJson'] = munged_dag

    print("Periodic execution of dag for dagid " + periodic_run_info['dagid'])
    return execute_dag.execute_dag(dag_event, None)

def munge_input_data(cognito_username, dag_id, period_type):
    modified = False
    dag_json = dag_utils.fetch_dag_json(cognito_username, dag_id)
    for node in dag_json['node']:
        if not 'input' in node:
            continue
        for inp in node['input']:
            if not 'time_spec' in inp:
                continue
            if len(inp['time_spec']) == 33:
                now = datetime.now()
                if period_type == 'hourly':
                    inp['time_spec'] = execute_dag.infinslice(now - timedelta(hours=1), now)
                    modified = True
                elif period_type == 'daily':
                    inp['time_spec'] = execute_dag.infinslice(now - timedelta(days=1), now)
                    modified = True
                elif period_type == 'weekly':
                    inp['time_spec'] = execute_dag.infinslice(now - timedelta(days=7), now)
                    modified = True
                elif period_type == 'monthly':
                    inp['time_spec'] = execute_dag.infinslice(now - timedelta(months=1), now)
                    modified = True
                elif period_type == 'yearly':
                    inp['time_spec'] = execute_dag.infinslice(now - timedelta(years=1), now)
                    modified = True
    if modified:
        print('munge_input_data: mungeable input found. DAG inputs were munged')
        return json.dumps(dag_json)
    else:
        print('munge_input_data: no mungeable input found. DAG unmodified')
        return None
