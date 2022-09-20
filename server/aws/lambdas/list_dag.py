
import json
import os
import logging
import uuid
import urllib.parse
import boto3

from utils import get_cognito_user
import ddb_mlflow_parallels_queries as ddb_pqrs

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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


def list_dag(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    body = event['body']
    dagid = None
    if body:
        print('body=' + str(body))
        bdict = urllib.parse.parse_qs(body)
        if 'id' in bdict:
            dagid = bdict['id']

    parallel_info_list = []
    if dagid:
        try:
            parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, dagid)
            parallel_info_list.append(parallel_info)
        except Exception as ex:
            logger.warning("list_dag: Exception in get_parallel: "+str(ex))
            pass
    else:
        try:
            dagids, _ = ddb_pqrs.get_parallels_for_user(cognito_username, cognito_username)
            if dagids:
                logger.info("dagid list for user: " + str(dagids))
                parallel_info_list = ddb_pqrs.get_parallel_info_multiple(cognito_username, dagids)
            else:
                logger.info("No dags found for user")
        except Exception as ex:
            logger.warning("list_dag: Exception in get_parallel: "+str(ex))
            pass
    logger.info('list_dag: Returning ' + json.dumps(parallel_info_list))
    return respond(None, {'xformDags': parallel_info_list})
