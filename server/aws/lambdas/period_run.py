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

import dag_utils, execute_dag, mlflow_utils

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
    
    # allow invocation of period_run() from api gateway and event bridge --> sqs --> period_run()
    item = json.loads(event.get('body')) if event.get('httpMethod') else event

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
    dag_event['periodic_run_frequency'] = periodic_run_info.get('period').get('type')
    dag_event['MLFLOW_TRACKING_URI'] = periodic_run_info.get('MLFLOW_TRACKING_URI')
    dag_event['MLFLOW_TRACKING_TOKEN'] = periodic_run_info.get('MLFLOW_TRACKING_TOKEN')
    dag_event['MLFLOW_CONCURRENT_URI'] = periodic_run_info.get('MLFLOW_CONCURRENT_URI')

    period_type = periodic_run_info['period']['type']
    dag_event['DROP_DEAD_TIME'] = get_drop_dead_time(period_type)

    # previous_run_status == None (never ran before) | running | failed | success
    previous_run_status, prev_start_time, prev_end_time \
        = get_previous_run_status(cognito_username, periodic_run_info)
    # previous_run_status == first_run | running | failed | success
    if not previous_run_status: previous_run_status = 'first_run'

    periodic_run_start_time = None
    if previous_run_status == 'running':
        logger.info('Previous run not finished yet, aborting current run')
        return respond('Previous run still in progress')
    elif previous_run_status == 'success':
        if prev_end_time:
            periodic_run_start_time = int(prev_end_time)
    elif previous_run_status == 'failed':
        if prev_start_time:
            periodic_run_start_time = int(prev_start_time)

    munged_dag, start_time, end_time = munge_input_data(cognito_username, dag_event['dagid'], period_type,
                                                        periodic_run_start_time)
    if munged_dag:
        dag_event['dagParamsJson'] = munged_dag
    dag_event['periodic_run_start_time'] = start_time
    dag_event['periodic_run_end_time'] = end_time
    dag_event['periodic_run_last_status'] = previous_run_status

    print("Periodic execution of dag for dagid " + periodic_run_info['dagid'])
    return execute_dag.execute_dag(dag_event, None)


def get_previous_run_status(cognito_username, periodic_run_info):
    dagid = periodic_run_info['dagid']
    exp_id = str(periodic_run_info['experiment_id'])
    period_type = periodic_run_info.get('period').get('type')

    ##Get the last dag execution record
    dag_execution_list = dag_utils.get_dag_execution_list(cognito_username, dagid)
    if not dag_execution_list:
        return None, None, None
    sorted_dag_execs = sorted(dag_execution_list, reverse=True, key=lambda a: a['start_time'])
    for dag_exec in sorted_dag_execs:
        parent_run_id = dag_exec['parent_run_id']
        auth_info = dag_exec['auth_info']
        if exp_id != mlflow_utils.get_experiment_id_from_run_id(parent_run_id):
            continue
        run_info = mlflow_utils.fetch_run_id_info(cognito_username, [], auth_info, parent_run_id)
        print("Previous parent run info: ", run_info)
        run_status = run_info['status'].lower()
        periodic_run_start_time = None
        periodic_run_end_time = None
        if 'params' in run_info:
            periodic_run_start_time = run_info['params'].get('periodic_run_start_time')
            periodic_run_end_time = run_info['params'].get('periodic_run_end_time')
        if run_status in ['running', 'unfinished', 'scheduled']:
            return 'running', periodic_run_start_time, periodic_run_end_time
        elif run_status in ['finished', 'success']:
            return 'success', periodic_run_start_time, periodic_run_end_time
        elif run_status in ['failed', 'killed']:
            return 'failed', periodic_run_start_time, periodic_run_end_time
        else:
            return None, None, None
    return None, None, None


def get_drop_dead_time(period_type):
    now = int(time.time())
    drop_dead_time = now + 24*60*60
    if period_type == 'hourly':
        drop_dead_time = now + 2 * 60 * 60
    elif period_type in ['daily', 'weekly', 'monthly']:
        drop_dead_time = now + 2 * 24 * 60 * 60
    elif period_type in 'yearly' :
        drop_dead_time = now + 7 * 24 * 60 * 60

    return drop_dead_time


def munge_input_data(cognito_username, dag_id, period_type, periodic_run_start_time):
    modified = False
    now = datetime.fromtimestamp(int(time.time()))
    dag_json = dag_utils.fetch_dag_json(cognito_username, dag_id)
    if period_type == 'hourly':
        if periodic_run_start_time:
            start_time = datetime.fromtimestamp(periodic_run_start_time)
        else:
            start_time = now - timedelta(hours=1)
        time_spec = execute_dag.infinslice(start_time, now)
        modified = True
    elif period_type == 'daily':
        if periodic_run_start_time:
            start_time = datetime.fromtimestamp(periodic_run_start_time)
        else:
            start_time = now - timedelta(days=1)
        time_spec = execute_dag.infinslice(start_time, now)
        modified = True
    elif period_type == 'weekly':
        if periodic_run_start_time:
            start_time = datetime.fromtimestamp(periodic_run_start_time)
        else:
            start_time = now - timedelta(days=7)
        time_spec = execute_dag.infinslice(start_time, now)
        modified = True
    elif period_type == 'monthly':
        if periodic_run_start_time:
            start_time = datetime.fromtimestamp(periodic_run_start_time)
        else:
            start_time = now - timedelta(months=1)
        time_spec = execute_dag.infinslice(start_time, now)
        modified = True
    elif period_type == 'yearly':
        if periodic_run_start_time:
            start_time = datetime.fromtimestamp(periodic_run_start_time)
        else:
            start_time = now - timedelta(years=1)
        time_spec = execute_dag.infinslice(start_time, now)
        modified = True
    elif period_type == 'once':
        start_time = now - timedelta(months=1)
        time_spec = execute_dag.infinsnap(now)
    else:
        raise Exception('Invalid period frequency')

    for node in dag_json['node']:
        if not 'input' in node:
            continue
        for inp in node['input']:
            if not 'time_spec' in inp:
                continue
            else:
                inp['time_spec'] = time_spec
                modified = True

    start_timestamp = int(datetime.timestamp(start_time))
    end_timestamp = int(datetime.timestamp(now))
    if modified:
        print('munge_input_data: mungeable input found. DAG inputs were munged')
        return json.dumps(dag_json), start_timestamp, end_timestamp
    else:
        print('munge_input_data: no mungeable input found. DAG unmodified')
        return None, start_timestamp, end_timestamp
