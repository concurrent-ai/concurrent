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
    dag_event['MLFLOW_TRACKING_URI'] = periodic_run_info.get('MLFLOW_TRACKING_URI')
    dag_event['MLFLOW_TRACKING_TOKEN'] = periodic_run_info.get('MLFLOW_TRACKING_TOKEN')
    dag_event['MLFLOW_CONCURRENT_URI'] = periodic_run_info.get('MLFLOW_CONCURRENT_URI')

    if 'data' in periodic_run_info:
        data = periodic_run_info['data']
    else:
        data = [{'type': 'no-input-data'}]
    dag_event['input'] = data
    print("Periodic execution of dag for dagid " + periodic_run_info['dagid'])
    return execute_dag.execute_dag(dag_event, None)
