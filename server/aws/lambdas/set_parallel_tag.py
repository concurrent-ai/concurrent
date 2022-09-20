import json
import os
import logging

from utils import get_cognito_user
import ddb_mlflow_parallels_queries as ddb_pqrs
import ddb_mlflow_parallels_txns as ddb_txns

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

def set_parallel_tag(event, context):
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
    if 'parallel_id' not in item:
        return respond(ValueError("Parallel id not specified"))

    parallel_id = item['parallel_id']
    logger.info('parallel_id=' + str(parallel_id))

    key = item['key']
    logger.info('key=' + str(key))
    value = item['value']
    logger.info('value=' + str(value))

    if not key or not value:
        return respond(ValueError("Tag not correctly specified"))

    parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, parallel_id)

    if not parallel_info:
        return respond(ValueError('Parallel not found for id=' + parallel_id))

    if 'tags' in parallel_info:
        tag_dict = {t['key']:t['value'] for t in parallel_info['tags']}
    else:
        tag_dict = {}

    ##Update tag_dict
    tag_dict[key] = value

    ##Convert back to array of tags
    new_tags = [{'key': k, 'value': v} for k,v in tag_dict.items()]

    try:
        ddb_txns.set_parallel_tags(cognito_username, parallel_id, str(new_tags))
    except Exception as ex:
        logger.warning("Error in setting tags for parallel_id="+parallel_id)
        return respond(ValueError('Setting parallel tags failed'))

    rv = dict()
    return respond(None, rv)


def remove_parallel_tag(event, context):
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
    if 'parallel_id' not in item:
        return respond(ValueError("Parallel id not specified"))

    parallel_id = item['parallel_id']
    logger.info('parallel_id=' + str(parallel_id))

    key = item['key']
    logger.info('key=' + str(key))

    if not key:
        return respond(ValueError("Tag not correctly specified"))

    parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, parallel_id)

    if not parallel_info:
        return respond(ValueError('Parallel not found for id=' + parallel_id))

    if 'tags' in parallel_info:
        tag_dict = {t['key']:t['value'] for t in parallel_info['tags']}
    else:
        tag_dict = {}

    ##Remove tag
    if key in tag_dict:
        tag_dict.pop(key)
    else:
        logger.info("Nothing to do, tag doesn't exist")
        rv = dict()
        return respond(None, rv)

    ##Convert back to array of tags
    new_tags = [{'key': k, 'value': v} for k,v in tag_dict.items()]

    try:
        ddb_txns.set_parallel_tags(cognito_username, parallel_id, str(new_tags))
    except Exception as ex:
        logger.warning("remove tag: Error in setting tags for parallel_id="+parallel_id)
        return respond(ValueError('Removing parallel tag failed'))

    rv = dict()
    return respond(None, rv)
