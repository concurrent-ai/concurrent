import json
import time
import urllib.request
from jose import jwk, jwt
from jose.utils import base64url_decode
import boto3
from utils import get_service_conf
import os

service_conf = None
jwks_cache = dict()
custom_token_cache = dict()
public_keys = None

def download_public_keys(context):
    print("Downloading public keys")
    function_arn_split = context.invoked_function_arn.split(':')
    region = function_arn_split[3]
    userpool_id = service_conf['cognitoUserPool']['S']
    global jwks_cache
    if region in jwks_cache and userpool_id in jwks_cache[region]:
        return jwks_cache[region][userpool_id]
    else:
        print("jwks cache miss, lookup URL")
        keys_url = 'https://cognito-idp.{}.amazonaws.com/{}/.well-known/jwks.json'.format(region, userpool_id)
        print(keys_url)
        with urllib.request.urlopen(keys_url) as f:
            response = f.read()
        keys = json.loads(response.decode('utf-8'))['keys']

        #Populate the cache
        if not jwks_cache.get(region):
            jwks_cache[region] = dict()
        jwks_cache[region][userpool_id] = keys
        return keys

def getResourceArn(context):
    function_arn_split = context.invoked_function_arn.split(':')
    region = function_arn_split[3]
    account_id = function_arn_split[4]
    print('Region=' + str(region) + ', account_id=' + str(account_id))
    global service_conf
    mlflow_api_id = service_conf['mlflowParallelsApiId']['S']
    arn = "arn:aws:execute-api:{0}:{1}:{2}/Prod/*/2.0/*".format(region, account_id, mlflow_api_id)
    return arn

def _allow_some_methodArns(event, context):
    method_arn = event['methodArn']
    # Example 'methodArn': 'arn:aws:execute-api:us-east-1:549374093768:zgdcrxeq92/Prod/GET/2.0/mlflow/experiments/list'
    parts = method_arn.split(':')
    path = parts[5]
    parts1 = path.split('/')
    if (parts1[2] == 'GET' and  parts1[3] == '2.0' and parts1[4] == 'mlflow' \
            and parts1[5] == 'parallels' \
            and (parts1[6] == 'cliclient_authorize' or parts1[6] == 'getversion')):
        return {
            'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Sid': 'Parallels-Cognito-GetVersion-Policy',
                        'Action': 'execute-api:Invoke',
                        'Effect': 'Allow',
                        'Resource': method_arn
                    }
                ]
            }
        }
    else:
        return None

def lambda_handler(event, context):
    print(event)

    ar = _allow_some_methodArns(event, context)
    if (ar != None):
        return ar

    #Load service_conf and public_keys once when module is loaded
    global service_conf, public_keys
    if (service_conf == None):
        success, status, service_conf = get_service_conf()
        if (success != True):
            print("Error. Failing auth on account of service_conf load failed="
                    + str(status))
            return False
        public_keys = download_public_keys(context)

    methodArn = getResourceArn(context)

    token_string = event['authorizationToken']
    if token_string.startswith('Bearer '):
        token_string = token_string[len('Bearer '):]

    if token_string.startswith('Custom '):
        token = token_string[len('Custom '):]
        print("Perform custom validation")
        auth_response = validate_custom_token(token, methodArn, "unknown")
        print(auth_response)
        return auth_response
    else:
        # This is ID token
        token = token_string

    # get the kid from the headers prior to verification
    try:
        headers = jwt.get_unverified_headers(token)
    except Exception as ex:
        return generatePolicy(None, "Deny", methodArn, None, None)

    kid = headers['kid']
    # search for the kid in the downloaded public keys
    key_index = -1
    for i in range(len(public_keys)):
        if kid == public_keys[i]['kid']:
            key_index = i
            break
    if key_index == -1:
        print('Public key not found in jwks.json')
        raise Exception("Internal Server Error")
    # construct the public key
    public_key = jwk.construct(public_keys[key_index])
    # get the last two sections of the token,
    # message and signature (encoded in base64)
    message, encoded_signature = str(token).rsplit('.', 1)
    # decode the signature
    decoded_signature = base64url_decode(encoded_signature.encode('utf-8'))
    # verify the signature
    if not public_key.verify(message.encode("utf8"), decoded_signature):
        print('Signature verification failed')
        return generatePolicy(None, "Deny", methodArn, None, None)
    print('Signature successfully verified')

    # since we passed the verification, we can now safely
    # use the unverified claims
    try:
        claims = jwt.get_unverified_claims(token)
    except Exception as ex:
        return generatePolicy(None, "Deny", methodArn, None, None)
    # additionally we can verify the token expiration
    if time.time() > claims['exp']:
        print('Token is expired')
        raise Exception("Unauthorized")
    print(claims)

    if claims['token_use'] == 'id':
        print("Auth with id token")
        ##This is an idToken
        principalId = claims['cognito:username']
        audience = claims['aud']
    else:
        print("Auth with access token")
        audience = claims['client_id']
        # Now validate token with cognito, this step is needed to prevent revoked tokens
        cognito_client = boto3.client("cognito-idp")
        try:
            response = cognito_client.get_user(AccessToken=token)
        except Exception as ex:
            print("Fatal Exception##")
            print(ex)
            return generatePolicy(None, "Deny", methodArn, audience, None)
        principalId = response['Username']
        if principalId != claims['username']:
            print('Inconsistent claims from cognito')
            return generatePolicy(principalId, "Deny", methodArn, audience, None)

    # if audience != app_client_id:
    #     print('Token was not issued for this audience')
    #     return generatePolicy(principalId, "Deny", methodArn, audience, None)

    if ('cognito:groups' in claims):
        authResponse = generatePolicy(principalId, "Allow", methodArn, audience, claims['cognito:groups'])
    else:
        authResponse = generatePolicy(principalId, "Allow", methodArn, audience, None)
    print(authResponse)
    return authResponse

def generatePolicy(principalId, effect, methodArn, audience, groups):
    authResponse = {}
    if principalId:
        authResponse["principalId"] = principalId

    if effect and methodArn:
        policyDocument = {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Sid': 'Parallels-Cognito-Authentication-Policy',
                    'Action': 'execute-api:Invoke',
                    'Effect': effect,
                    'Resource': methodArn
                }
            ]
        }
        authResponse['policyDocument'] = policyDocument
        context = dict()
        if principalId:
            context["cognito:username"] = principalId
        if audience:
            context["aud"] = audience
        if groups:
            # only string, int or boolean allowed in context. No arrays
            context["groups"] = ",".join(groups)
        if context:
            authResponse['context'] = context

    return authResponse

def validate_custom_token(customToken, methodArn, audience):
    ##This custom token is validated from dynamodb
    queue_message_uuid, token = customToken.split(':')

    ddb_client = boto3.client("dynamodb")

    table_name = os.environ['CUSTOM_TOKENS_TABLE']

    ##Check in cache
    global custom_token_cache
    token_in_db = None
    if queue_message_uuid in custom_token_cache:
        token_in_db, user_name, groups, token_expiry = custom_token_cache[queue_message_uuid]
        if time.time() < token_expiry:
            print("Token found in cache")
        else:
            print("Cached token expired")
            token_in_db = None

    if not token_in_db:
        print("Perform db lookup")
        key = dict()
        hk = dict()
        hk['S'] = queue_message_uuid
        key['queue_message_uuid'] = hk
        try:
            result = ddb_client.get_item(TableName=table_name, Key=key)
            token_in_db = result['Item']['token']['S']
            user_name = result['Item']['cognito_username']['S']
            if 'groups' in result['Item']:
                groups_str = result['Item']['groups']['S']
                groups = json.loads(groups_str)
            else:
                groups = None
            if 'token_expiry' in result['Item']:
                token_expiry = int(result['Item']['token_expiry']['S'])
                if time.time() < token_expiry:
                    custom_token_cache[queue_message_uuid] = (token_in_db, user_name, groups, token_expiry)
                else:
                    token_in_db = None
        except Exception as ex:
            print("Couldn't validate token : "+str(ex))
            return generatePolicy(None, "Deny", methodArn, audience, None)

    if (token_in_db and token_in_db == token):
        return generatePolicy(user_name, "Allow", methodArn, audience, groups)
    else:
        print("Incorrect token")
        return generatePolicy(user_name, "Deny", methodArn, audience, groups)
