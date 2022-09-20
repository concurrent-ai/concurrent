import boto3
from botocore.exceptions import ClientError
import os
import secrets
import time
import json
import uuid


PARALLELS_SCHEMA_VERSION = 'v000'
DAG_INFO_TABLE = os.environ['DAG_TABLE']

def get_cognito_user(event):
    request_context = event['requestContext']
    authorizer = request_context['authorizer']
    cognito_username = authorizer['principalId']
    groups = None
    if ('groups' in authorizer):
        groups = authorizer['groups'].split(",")
    print("user=" + str(cognito_username) +", groups=" +str(groups))
    return cognito_username, groups

cached_service_conf = None
def get_service_conf():
    global cached_service_conf
    if (cached_service_conf != None):
        return True, '', cached_service_conf

    result = None
    client = boto3.client('dynamodb')
    try:
        result = client.get_item(TableName = os.environ['SERVICE_CONF_TABLE'],
                Key={'configVersion': {'N': '1'}})
    except Exception as ex:
        print(str(ex))
        return False, str(ex), None
    if (result != None):
        item = result['Item']
        cached_service_conf = item
        return True, '', item
    return False, 'Cannot find service config', None

cached_cognito_domain = None
def cognito_domain(conf):
    global cached_cognito_domain
    if cached_cognito_domain:
        return cached_cognito_domain
    client = boto3.client('cognito-idp')
    try:
        result = client.describe_user_pool(UserPoolId=conf['cognitoUserPool']['S'])
        cached_cognito_domain = result['UserPool']['Domain']
        return cached_cognito_domain
    except Exception as ex:
        print(str(ex))
        return None


cached_cognito_callback_url = None
def cognito_callback_url(conf):
    global cached_cognito_callback_url
    if cached_cognito_callback_url:
        return cached_cognito_callback_url
    client = boto3.client('cognito-idp')
    try:
        result = client.describe_user_pool_client(UserPoolId=conf['cognitoUserPool']['S'],
                ClientId=conf['cognitoClientId']['S'])
        cached_cognito_callback_url = result['UserPoolClient']['CallbackURLs'][0]
        return cached_cognito_callback_url
    except Exception as ex:
        print(str(ex))
        return None

def lookup_subscriber_by_name(cognito_username):
    """ returns 
    success: a boolean to indicate success r failure
    status: a string to indicate reason for failure if any
    item: a row from infinstor-subscriber ddb table
    """
    print('lookup_subscriber_by_name: Looking up cognito username ' + cognito_username)
    result = None
    client = boto3.client('dynamodb')
    try:
        result = client.query(TableName = os.environ['SUBSCRIBERS_TABLE'],IndexName='username-GSI',\
                KeyConditionExpression = 'userName = :un',\
                ExpressionAttributeValues={':un': {'S': cognito_username}})
    except Exception as ex:
        print('Could not find subscriber ' + cognito_username)
        return False, 'Cannot find user', None

    if (result and 'Items' in result):
        item = result['Items'][0]
        return True, '', item
    return False, 'Cannot find user', None

def lookup_subscriber_by_customer_id(customerId):
    """ returns
    success: a boolean to indicate success r failure
    status: a string to indicate reason for failure if any
    item: a row from infinstor-subscriber ddb table
    """
    print('lookup_subscriber_by_customer_id: Looking up customerId=' + customerId)
    result = None
    client = boto3.client('dynamodb')
    try:
        result = client.query(TableName = os.environ['SUBSCRIBERS_TABLE'],
                KeyConditionExpression='customerId = :ci',
                ExpressionAttributeValues={':ci': {'S': customerId}})
    except Exception as ex:
        print('Could not find subscriber for customerId ' + str(customerId))
        return False, 'Could not find ds user', None
    else:
        if (result != None and 'Items' in result):
            item = result['Items'][0] # we should return the most capable prod id and not the first
            return True, '', item
        return False, 'Cannot find user', None

def add_cognito_user_specific_configs(subs, cognito_username):
    print('add_cognito_user_specific_configs: no user specific configs in parallels yet')
    return

subscriber_info_cache = {}
def get_subscriber_info(cognito_username):
    """ returns 
    success: a boolean to indicate success r failure
    status: a string to indicate reason for failure if any
    item: a row from infinstor-subscriber ddb table
    """
    global subscriber_info_cache
    if cognito_username in subscriber_info_cache:
        print("Found subscriber info in cache: " + str(subscriber_info_cache[cognito_username]))
        return subscriber_info_cache[cognito_username]
    success, status, conf = get_service_conf()
    ext_oauth = conf['isExternalAuth']['S'] == 'true' if conf.get('isExternalAuth', False) else False
    if (ext_oauth == True):
        print("get_subscriber_info: Service is configured for external oauth")
        success, status, subs = lookup_subscriber_by_name('root')
        if success:
            subscriber_info_cache[cognito_username] = (success, status, subs)
        return success, status, subs

    print("get_subscriber_info: Service is not configured for external oauth")
    client = boto3.client('cognito-idp')
    result = None
    retryInterval = 0.8
    while retryInterval < 30:
        try:
            pool_id = os.environ['POOL_ID']
            print("Pool ID is " + pool_id)
            result = client.admin_get_user(UserPoolId = pool_id,\
                    Username=cognito_username)
        except botocore.exceptions.ClientError as err:
            response = err.response
            print("Failed to get_user :" + str(response))
            if (response and response.get("Error", {}).get("Code") ==
                    "TooManyRequestsException"):
                print("Continue for TooManyRequestsException exception.")
                #randomize the retry interval
                time.sleep(retryInterval + random.uniform(0,1))
                #exponential backoff
                retryInterval = 2*retryInterval
                continue
        break
    if not result:
        return False, "Failure in subscriber lookup", None

    attrs = result['UserAttributes']
    customerId = None
    for attr in attrs:
        if (attr['Name'] == 'custom:customerId'):
            customerId = attr['Value']

    if (customerId == None or len(customerId) == 0):
        success, status, subs = lookup_subscriber_by_name(cognito_username)
        if success:
            subscriber_info_cache[cognito_username] = (success, status, subs)
        return success, status, subs
    else:
        success, status, subs = lookup_subscriber_by_customer_id(customerId)
        if success:
            add_cognito_user_specific_configs(subs, cognito_username)
            subscriber_info_cache[cognito_username] = (success, status, subs)
        return success, status, subs

def get_custom_token(cognito_username, groups):
    """ generate message uuid and custom token """
    client = boto3.client('dynamodb')

    table_name = os.environ['CUSTOM_TOKENS_TABLE']

    paginator = client.get_paginator('scan')
    op_params = {
            'TableName': table_name,
            'FilterExpression': 'cognito_username = :cu',
            'ExpressionAttributeValues': {':cu': {'S': cognito_username}}
            }
    pi = paginator.paginate(**op_params)
    found_token_uuid = None
    for pg in pi:
        if ('Items' in pg):
            for one_item in pg['Items']:
                print('Returning existing token ' + one_item['queue_message_uuid']['S']
                        + ' for ' + cognito_username)
                if 'token_expiry' in one_item:
                    token_expiry = int(one_item['token_expiry']['S'])
                    if time.time() < token_expiry:
                        return one_item['queue_message_uuid']['S'], one_item['token']['S']
                found_token_uuid = one_item['queue_message_uuid']['S']

    if found_token_uuid:
        queue_message_uuid = found_token_uuid
    else:
        queue_message_uuid = str(uuid.uuid1())
    token = secrets.token_urlsafe(256)

    item = {
        "queue_message_uuid": {"S": queue_message_uuid},
        "token": {"S": token},
        "cognito_username": {"S": cognito_username},
        "token_expiry": {"S": str(int(time.time()) + 7*24*3600)}  # 7 days
    }
    if groups:
        item['groups'] = {"S": json.dumps(groups)}

    try:
        client.put_item(TableName=table_name, Item=item)
    except Exception as ex:
        print("Couldn't put item in dynamodb")
        raise

    return queue_message_uuid, token

#Creates a fake context, useful in lambda to lambda invocation
def create_request_context(cognito_username):
    auth_info = {'aud': 'unknown', 'principalId': cognito_username}
    request_context = {'authorizer': auth_info}
    return request_context


def get_ddb_boto3_client_parallels(cognito_username):
    #client, _ = get_ddb_boto3_client(cognito_username)
    #return DAG_INFO_TABLE, PARALLELS_SCHEMA_VERSION, client
    return DAG_INFO_TABLE, PARALLELS_SCHEMA_VERSION, boto3.client('dynamodb')


def extract_url_kv_params(body):
    items = {}
    bs = body.split('&')
    for obs in bs:
        obss = obs.split('=')
        if len(obss) == 2:
            items[obss[0]] = obss[1]
    return items