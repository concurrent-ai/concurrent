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

