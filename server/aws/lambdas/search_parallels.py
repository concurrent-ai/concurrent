import json
import os
import logging

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

def search_parallels(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    qs = event['queryStringParameters']
    logger.info(qs)

    if 'parallel_name' in qs:
        parallel_name = qs['parallel_name']
    else:
        logger.warning('Error: parallel_name not specified')
        return respond(ValueError('parallel_name must be specified'))

    parallel_name_list = []
    id_list = ddb_pqrs.search_parallel_ids_from_name(cognito_username, parallel_name)

    parallels_visible_for_user, _ = ddb_pqrs.get_parallels_for_user(cognito_username, cognito_username)
    parallels_visible_for_user = set(parallels_visible_for_user)

    if groups:
        for g in groups:
            group_visible, _ = ddb_pqrs.get_parallels_for_group(cognito_username, g)
            parallels_visible_for_user.update(group_visible)

    for p_id in id_list:
        #filter out parallels that are not visible for the user
        if p_id not in parallels_visible_for_user:
            continue
        parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, p_id)
        parallel_name_list.append(parallel_info['parallel_name'])

    rv = dict()
    rv['parallels'] = parallel_name_list
    return respond(None, rv)