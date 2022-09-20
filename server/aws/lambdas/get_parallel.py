import json
import os
import logging

from utils import get_cognito_user
import ddb_mlflow_parallels_queries as ddb_pqrs
import parallel_authorization

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

def get_parallel(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if operation != 'GET':
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    qs = event['queryStringParameters']
    logger.info(qs)

    parallel_info = None
    parallel_id = None
    parallel_name = None
    if 'parallel_id' in qs:
        parallel_id = qs['parallel_id']
        parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, parallel_id)
    elif 'parallel_name' in qs:
        parallel_name = qs['parallel_name']
        parallel_info = ddb_pqrs.get_parallel_by_name(cognito_username, parallel_name)

    if not parallel_info:
        return respond(ValueError('Parallel not found for id=' + str(operation) + ', or name='+str(parallel_name)))

    authorized = parallel_authorization.check_authorization(
        cognito_username, groups, parallel_info['parallel_id'], 'parallel/get')

    if not authorized:
        emsg = 'get_parallel: {0} not authorized'.format(cognito_username)
        logger.info(emsg)
        return parallel_authorization.authorization_error(emsg)

    parallel_json = parallel_info['parallel_json']
    parallel_obj = json.loads(parallel_json)
    parallel_obj['id'] = parallel_info['parallel_id']
    parallel_obj['name'] = parallel_info['parallel_name']
    parallel_info['parallel_json'] = parallel_info['dagJson'] = json.dumps(parallel_obj)

    rv = dict()
    rv['parallel'] = parallel_info
    return respond(None, rv)

