import json
import os
import logging

from utils import get_cognito_user
import dag_utils

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

def get_dag_execution(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    qs = event['queryStringParameters']
    logger.info(qs)
    if 'dagid' not in qs:
        err = "Missing parameter: dagid not found"
        logger.error(err)
        return respond(ValueError(err))

    dagid = qs['dagid']
    dag_execution_id = None
    if 'dag_execution_id' in qs:
        dag_execution_id = qs['dag_execution_id']

    try:
        if dag_execution_id:
            dag_execution_info = dag_utils.get_dag_execution_record(cognito_username, dagid, dag_execution_id)
        else:
            dag_execution_info = dag_utils.get_dag_execution_list(cognito_username, dagid)
    except Exception as ex:
        err = "get_dag_execution: Error {0}".format(str(ex))
        logger.error(err)
        return respond(ValueError(err))

    logger.info("dag_exec_info=%s", str(dag_execution_info))

    rv = dict()
    rv['dag_execution_info'] = dag_execution_info
    return respond(None, rv)
