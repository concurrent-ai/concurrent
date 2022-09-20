import json
import os
import logging
import time
import random

from utils import get_service_conf, get_subscriber_info, get_cognito_user, get_custom_token, extract_url_kv_params
import ddb_mlflow_parallels_txns as ddb_ptxns
import ddb_mlflow_parallels_queries as ddb_pqrs
from botocore.exceptions import ClientError
from urllib.parse import unquote
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

def create_or_update_parallel(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    item = extract_url_kv_params(event['body'])
    logger.info('payload item=' + str(item))

    if 'parallel_id' in item:
        parallel_id = item['parallel_id']
    else:
        parallel_id = None

    parallel_name = item.get('parallel_name')
    parallel_json = item.get('parallel_json')
    description = item.get('description')
    experiment_id = item.get('experiment_id')

    if parallel_json:
        parallel_json = unquote(parallel_json)

    if parallel_id:
        authorized = parallel_authorization.check_authorization(
            cognito_username, groups, parallel_id, 'parallel/update')
        if not authorized:
            emsg = 'update_parallel: {0} not authorized'.format(cognito_username)
            logger.info(emsg)
            return parallel_authorization.authorization_error(emsg)
        ##Update an existing parallel
        ddb_ptxns.update_parallel(cognito_username, parallel_id, parallel_json, description, experiment_id)
        rv = dict()
        return respond(None, rv)
    else:
        ##Create new parallel
        if not parallel_name or not parallel_json:
            return respond(ValueError("Parallel name or json not specified"))
        retries = 3
        success = False
        while retries > 0:
            parallel_id = "DAG" + str(int(time.time() * 1000))
            try:
                ddb_ptxns.create_new_parallel(cognito_username, groups, parallel_id,
                           parallel_name, parallel_json, description, cognito_username)
                success = True
                break
            except ClientError as e:
                retries -= 1
                time.sleep(round(random.uniform(0, 0.1), 3))
                continue

        if success:
            rv = {'parallel_id': parallel_id}
            logger.info(json.dumps(rv))
            return respond(None, rv)
        else:
            return respond("Failed to create parallel")


def rename_parallel(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    item = json.loads(event['body'])
    logger.info('payload item=' + str(item))

    parallel_id = item['parallel_id']
    new_parallel_name = item['parallel_name']

    parallel = ddb_pqrs.get_parallel_by_id(cognito_username, parallel_id)
    old_name = parallel['parallel_name']

    if old_name == new_parallel_name:
        logger.info("Nothing to do, same name requested " + new_parallel_name)
        return respond(ValueError("Nothing to do, same name requested " + new_parallel_name), None)

    try:
        ddb_ptxns.rename_parallel(cognito_username, parallel_id, old_name, new_parallel_name)
        return respond(None, dict())
    except Exception as ex:
        logger.warning("Failed to rename: " + str(ex))
        return respond("Rename failed", None)


def delete_parallel(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    item = json.loads(event['body'])
    logger.info('payload item=' + str(item))

    parallel_id = item['parallel_id']
    parallel = ddb_pqrs.get_parallel_by_id(cognito_username, parallel_id)
    parallel_name = parallel['parallel_name']

    roles = ddb_pqrs.get_parallel_roles(cognito_username, parallel_id)
    user_list = roles['user_roles'].keys()
    group_list = roles['group_roles'].keys()

    try:
        ddb_ptxns.delete_parallel(cognito_username, parallel_id, parallel_name, user_list, group_list)
        return respond(None, dict())
    except Exception as ex:
        logger.warning("Deletion failed for parallel id " + parallel_id +": " + str(ex))
        return respond("Deletion failed", None)





