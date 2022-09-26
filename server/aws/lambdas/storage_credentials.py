import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from utils import get_cognito_user

STORAGE_CREDENTIALS_TABLE = os.environ['STORAGE_CREDENTIALS_TABLE']

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


def get_user_buckets(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    qs = event['queryStringParameters']

    bucket = None
    if qs and 'bucket' in qs:
        bucket = qs['bucket']

    creds_list = query_storage_credentials(cognito_username, bucket)

    if creds_list:
        bucket_list = [c['bucket'] for c in creds_list]
        print('Returning bucket list: ', bucket_list)
        return respond(None, {'buckets': bucket_list})
    else:
        return respond(None, {'buckets': []})


def query_storage_credentials(cognito_username, bucket):
    if bucket:
        logger.info("Get credentials for bucket {} for user {}".format(bucket, cognito_username))
    else:
        logger.info("Query credentials for user {}".format(cognito_username))

    ddb_client = boto3.client('dynamodb')
    if bucket:
        try:
            response = ddb_client.get_item(TableName=STORAGE_CREDENTIALS_TABLE,
                                      Key={
                                          'username': {'S': cognito_username},
                                          'bucket': {'S': bucket}
                                      })
        except Exception as ex:
            logger.warning("Storage credentials query failed: " + str(ex))
            return []

        creds = None
        if 'Item' in response:
            item = response['Item']
            creds = {
                'bucket' : bucket,
                'external_id': item['external_id']['S'],
                'iam_role': item['iam_role']['S']
            }
            return creds
        return [creds]
    else:
        try:
            response = ddb_client.query(TableName=STORAGE_CREDENTIALS_TABLE,
                                        KeyConditionExpression='username = :un',
                                        ExpressionAttributeValues={':un': {'S': cognito_username}})
        except Exception as ex:
            logger.warning("Storage credentials query failed: " + str(ex))
            return []

        creds_list = []
        if 'Items' in response:
            for item in response['Items']:
                creds = {
                    'bucket': item['bucket']['S'],
                    'external_id': item['external_id']['S'],
                    'iam_role': item['iam_role']['S']
                }
                creds_list.append(creds)
        return creds_list


def add_user_bucket(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    body = event['body']
    item = json.loads(body)

    bucket = item['bucket']
    iam_role = item['iam_role']
    external_id = item['external_id']

    storage_type = 'aws-s3' ##TODO: Support other storage types
    record = {
        'username': {'S': cognito_username},
        'bucket': {'S': bucket},
        'iam_role': {'S': iam_role},
        'external_id': {'S': external_id},
        'storage_type': {'S': storage_type},
    }

    ddb_client = boto3.client('dynamodb')
    try:
        ddb_client.put_item(TableName=STORAGE_CREDENTIALS_TABLE, Item=record)
    except Exception as ex:
        logger.warning("Failed to add bucket: " + str(ex))
        return respond("Failed to add bucket", dict())

    return respond(None, dict())


def remove_user_bucket(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    body = event['body']
    item = json.loads(body)

    bucket = item['bucket']
    ddb_client = boto3.client('dynamodb')

    key = {
        'username': {'S': cognito_username},
        'bucket': {'S': bucket}
    }
    try:
        ddb_client.delete_item(TableName=STORAGE_CREDENTIALS_TABLE, Key=key)
    except Exception as ex:
        logger.warning("remove_user_bucket failed: " + str(ex))
        return respond("Remove failed", dict())

    return respond(None, dict())


