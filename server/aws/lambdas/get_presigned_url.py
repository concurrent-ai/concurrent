
import json
import os
import logging
import uuid
from urllib.parse import urlparse, quote, unquote

from utils import get_cognito_user
import boto3
from storage_credentials import query_storage_credentials
import botocore
import botocore.client

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

def get_presigned_url(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, _ = get_cognito_user(event)

    qs = event['queryStringParameters']
    logger.info(qs)

    bucket = None
    path = None
    if 'bucket' in qs:
        bucket = qs['bucket']
    if 'path' in qs:
        path = qs['path']

    if not path or not bucket:
        logger.info('bucket and path are required')
        return respond(ValueError('bucket and path are required'))

    if ('method' in qs):
        method = qs['method']
    else:
        method = 'get_object'

    creds = query_storage_credentials(cognito_username, bucket)

    if not creds:
        msg = "No credentials available for bucket {} for user {}".format(bucket, cognito_username)
        logger.warning(msg)
        return respond(msg)

    if method == 'list_objects_v2':
        params = {'Bucket': bucket, 'Prefix': path, 'Delimiter': '/'}
        if 'ContinuationToken' in qs:
            params['ContinuationToken'] = unquote(qs['ContinuationToken'])
    else:
        params = {'Bucket': bucket, 'Key': path}
        if 'Marker' in qs:
            params['Marker'] = qs['Marker']

    if 'StartAfter' in qs:
        params['StartAfter'] = qs['StartAfter']
    if 'MaxKeys' in qs:
        params['MaxKeys'] = qs['MaxKeys']

    sts_client = boto3.client('sts')
    if 'external_id' in creds:
        assumed_role_object = sts_client.assume_role(
            RoleArn=creds['iam_role'],
            ExternalId=creds['external_id'],
            RoleSessionName=str(uuid.uuid4()))
    else:
        assumed_role_object = sts_client.assume_role(
            RoleArn=creds['iam_role'],
            RoleSessionName=str(uuid.uuid4()))

    credentials = assumed_role_object['Credentials']
    # https://stackoverflow.com/questions/57950613/boto3-generate-presigned-url-signaturedoesnotmatch-error; 
    # to avoid this error from generate_presigned_url('list_objects_v2'): <Error><Code>SignatureDoesNotMatch</Code><Message>The request signature we calculated does not match the signature you provided. Check your key and signing method.</Message>    
    client = boto3.client("s3",
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken'],
        config=botocore.client.Config(signature_version='s3v4')
    )

    ps_url = client.generate_presigned_url(method, Params=params, ExpiresIn = (24*60*60))

    logger.info('Presigned URL is ' + str(ps_url))
    ##Handle quoting of continuation token
    if 'ContinuationToken' in params:
        url_comps = urlparse(ps_url)
        query_comps = url_comps.query.split('&')
        for i in range(len(query_comps)):
            if query_comps[i].startswith('continuation-token='):
                ct_quoted = quote(params['ContinuationToken'])
                query_comps[i] = 'continuation-token=' + ct_quoted
        query = '&'.join(query_comps)
        url_comps._replace(query=query)
        ps_url = url_comps.geturl()
        logger.info('Updated Presigned URL is ' + str(ps_url))

    if 'Marker' in params:
        url_comps = urlparse(ps_url)
        query_comps = url_comps.query.split('&')
        for i in range(len(query_comps)):
            if query_comps[i].startswith('marker='):
                ct_quoted = quote(params['Marker'])
                query_comps[i] = 'marker=' + ct_quoted
        query = '&'.join(query_comps)
        url_comps._replace(query=query)
        ps_url = url_comps.geturl()
        logger.info('Updated Presigned URL is ' + str(ps_url))

    if (ps_url == None):
        return respond(ValueError('Failed to create presigned URL'))
    else:
        rv = {"presigned_url": ps_url}
        logger.info(json.dumps(rv))
        return respond(None, rv)