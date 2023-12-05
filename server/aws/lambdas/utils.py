import datetime
import traceback
import boto3
import botocore
from botocore.exceptions import ClientError
import os
import secrets
import time
import json
import uuid
import random
import io

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key

from typing import Any, TYPE_CHECKING, Tuple, Union
if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import ExecuteStatementOutputTypeDef
else:
    DynamoDBClient = object
    ExecuteStatementOutputTypeDef = object

if TYPE_CHECKING:
    from mypy_boto3_acm_pca import ACMPCAClient
    from mypy_boto3_acm_pca.type_defs import IssueCertificateResponseTypeDef, ValidityTypeDef, GetCertificateResponseTypeDef, ListCertificateAuthoritiesResponseTypeDef, CertificateAuthorityTypeDef, CertificateAuthorityConfigurationTypeDef
    from mypy_boto3_acm_pca.waiter import CertificateIssuedWaiter
    
    from mypy_boto3_sts import STSClient
    from mypy_boto3_sts.type_defs import AssumeRoleResponseTypeDef
else:
    ACMPCAClient=object
    IssueCertificateResponseTypeDef=object; ValidityTypeDef=object; GetCertificateResponseTypeDef=object; ListCertificateAuthoritiesResponseTypeDef=object; CertificateAuthorityTypeDef=object
    CertificateIssuedWaiter=object; CertificateAuthorityConfigurationTypeDef=object
    
    STSClient = object
    AssumeRoleResponseTypeDef = object

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

is_external_oauth = None

def update_is_external_oauth():
    global is_external_oauth
    if (is_external_oauth == None):
        print("is_external_oauth: Checking to see if service is configured for external oauth")
        success, status, conf = get_service_conf()
        if (not success):
            print("update_is_external_oauth: Error getting service conf")
            return
        if 'useDirectAad' in conf and conf['useDirectAad']['S'] == 'true':
            print("update_is_external_oauth: using direct aad. external oauth is true")
            is_external_oauth = True
            return
        result = None
        client = boto3.client('cognito-idp')
        retryInterval = 0.8
        while retryInterval < 30:
            try:
                result = client.describe_user_pool_client(UserPoolId = conf['cognitoUserPool']['S'],
                        ClientId=conf['cognitoMlflowuiClientId']['S'])
            except botocore.exceptions.ClientError as err:
                response = err.response
                print("Failed to get_user :" + str(response), exc_info=err)
                if (response and response.get("Error", {}).get("Code") ==
                        "TooManyRequestsException"):
                    print("Continue for TooManyRequestsException exception.")
                    # randomize the retry interval
                    time.sleep(retryInterval + random.uniform(0,1))
                    # exponential backoff
                    retryInterval = 2 * retryInterval
                    continue
            break
        if not result:
            raise ("Could not find subscriber info")
        upc = result['UserPoolClient']
        if ('SupportedIdentityProviders' in upc):
            sip = upc['SupportedIdentityProviders']
            for os in sip:
                if (os != 'COGNITO'):
                    print("is_external_oauth: Found supported identity provider "
                        + os + ", hence is_external_oauth is True")
                    is_external_oauth = True
                    return
            print("is_external_oauth: Did not find any identity provider other than COGNITO, hence is_external_oauth is False")
            is_external_oauth = False
        else:
            print("is_external_oauth: No key SupportedIdentityProviders. hence is_external_oauth is False")
            is_external_oauth = False

def check_if_external_oauth():
    update_is_external_oauth()
    global is_external_oauth
    return is_external_oauth

subscriber_info_cache = {}
def get_subscriber_info(cognito_username:str, ignore_cache:bool=False) -> Tuple[bool, str, dict]:
    """ returns 
    success (bool): a boolean to indicate success r failure
    status (str): a string to indicate reason for failure if any
    item (dict): a row from infinstor-subscriber ddb table
    """
    global subscriber_info_cache
    if not ignore_cache and cognito_username in subscriber_info_cache:
        print("Found subscriber info in cache: " + str(subscriber_info_cache[cognito_username]))
        return subscriber_info_cache[cognito_username]

    update_is_external_oauth()
    global is_external_oauth
    if (is_external_oauth == True):
        print("get_subscriber_info: Service is configured for external oauth")
        success, status, subs = lookup_subscriber_by_name('root')
        if cognito_username == 'root':
            subs['isSecondaryUser'] = False
        else:
            subs['isSecondaryUser'] = True
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
        subs['isSecondaryUser'] = False
        if success:
            subscriber_info_cache[cognito_username] = (success, status, subs)
        return success, status, subs
    else:
        success, status, subs = lookup_subscriber_by_customer_id(customerId)
        subs['isSecondaryUser'] = True
        if success:
            add_cognito_user_specific_configs(subs, cognito_username)
            subscriber_info_cache[cognito_username] = (success, status, subs)
        return success, status, subs

def update_subscriber_info(cognito_username:str, customer_id:str, product_code:str, update_dict:dict) -> Tuple[bool, Union[str, list]]:
    """
    updates the infinstor-subscriber table.  Also refreshes subscriber_info_cache with the updated values.

    Args:
        cognito_username (str): _description_
        subs_ddb_item (dict): _description_
        update_dict (dict): dict with ddb item's field_name, field_value.  These will be used to create a PartiQL update statement

    Returns:
        Tuple[bool, Union[str, list]]: returns the tuple (success=True|False, string (error string on error) or list (the updated subscriber ddb items) )
    """
    try:
        # CREATE TABLE infinstor-Subscribers (customerId STRING HASH KEY, productCode STRING RANGE KEY, userName STRING, THROUGHPUT (0, 0))GLOBAL ALL INDEX ('username-GSI', userName, productCode, THROUGHPUT (0, 0));
        #
        # https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ql-reference.update.html
        # UPDATE  table  
        # [SET | REMOVE]  path  [=  data] […]
        # WHERE condition [RETURNING returnvalues]
        # <returnvalues>  ::= [ALL OLD | MODIFIED OLD | ALL NEW | MODIFIED NEW] *
        set_clauses:str = ""
        for key,val in update_dict.items():
            set_clauses = set_clauses + f" SET {key}='{val}' "
        # Note: table name must be double quoted due to the use of '-' in the name: infinstor-Subscribers
        # Error: ValidationException: Where clause does not contain a mandatory equality on all key attributes
        update_stmt:str = f"UPDATE \"{os.environ['SUBSCRIBERS_TABLE']}\" {set_clauses} WHERE customerId = '{customer_id}' AND productCode = '{product_code}' RETURNING ALL NEW *"
        print(f"Executing update_stmt for subscriber {cognito_username} = {update_stmt}")
        
        ddb_client:DynamoDBClient
        _ , _, ddb_client = get_ddb_boto3_client_parallels(cognito_username)
        if not ddb_client: return False, "Unable to get ddb_client for service"
        
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.execute_statement
        # https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_ExecuteStatement.html
        # response = {'Items': [{...}, {...}, {...}, {...}, {...}, {...}, {...}, {...}, {...}, ...], 'ResponseMetadata': {'RequestId': 'CHBDU0TEJ6UH82VNOMPA9F8I3NVV4KQNSO5AEMVJF66Q9ASUAAJG', 'HTTPStatusCode': 200, 'HTTPHeaders': {...}, 'RetryAttempts': 0}}
        exec_stmt_resp:ExecuteStatementOutputTypeDef = ddb_client.execute_statement(Statement=update_stmt)
        ddb_http_status_code:int = exec_stmt_resp.get('ResponseMetadata').get('HTTPStatusCode')
        if ddb_http_status_code != 200: return False, f"dynamodb http status code={ddb_http_status_code} headers={exec_stmt_resp['ResponseMetadata'].get('HTTPHeaders')}"
        
        success:bool; err_str:str; sub_ddb_item:dict
        # force update the subscriber_info_cache used by get_subscriber_info()
        success, err_str, sub_ddb_item = get_subscriber_info(cognito_username, ignore_cache=True)
        
        return (True, [sub_ddb_item]) if success else (False, f"get_subscriber_info() error={err_str}")
    except Exception as e:
        print(f"Exception caught during ddb update subscriber: {e}")
        traceback.print_exc()
        return False, str(e)

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
                    if time.time() <= token_expiry - 60*60:
                        token_info = {
                            'queue_message_uuid': one_item['queue_message_uuid']['S'],
                            'token': one_item['token']['S'],
                            'expiry': token_expiry
                        }
                        return token_info
                found_token_uuid = one_item['queue_message_uuid']['S']

    if found_token_uuid:
        queue_message_uuid = found_token_uuid
    else:
        queue_message_uuid = str(uuid.uuid1())
    token = secrets.token_urlsafe(256)
    token_expiry = int(time.time()) + 7*24*3600
    item = {
        "queue_message_uuid": {"S": queue_message_uuid},
        "token": {"S": token},
        "cognito_username": {"S": cognito_username},
        "token_expiry": {"S": str(token_expiry)}  # 7 days
    }
    if groups:
        item['groups'] = {"S": json.dumps(groups)}

    try:
        client.put_item(TableName=table_name, Item=item)
    except Exception as ex:
        print("Couldn't put item in dynamodb")
        raise

    token_info = {
        'queue_message_uuid': queue_message_uuid,
        'token': token,
        'expiry': token_expiry
    }

    return token_info

#Creates a fake context, useful in lambda to lambda invocation
def create_request_context(cognito_username):
    auth_info = {'aud': 'unknown', 'principalId': cognito_username}
    request_context = {'authorizer': auth_info}
    return request_context


def get_ddb_boto3_client_parallels(cognito_username) -> Tuple[str, str, DynamoDBClient]:
    """
    _summary_

    _extended_summary_

    Args:
        cognito_username (_type_): _description_

    Returns:
        Tuple[str, str, DynamoDBClient]: returns 'DAG_INFO_TABLE' name, PARALLELS_SCHEMA_VERSION, DynamoDBClient
    """
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


def is_user_admin(cognito_username):
    success, status, subs = get_subscriber_info(cognito_username)
    if 'isSecondaryUser' in subs:
        return not subs['isSecondaryUser']
    else:
        return False


def get_subscriber_name(cognito_username):
    success, status, subs = get_subscriber_info(cognito_username)
    return subs['userName']['S']

def _cert_expired(cert_pem:str) -> bool:
    # https://cryptography.io/en/latest/x509/reference/#cryptography.x509.load_pem_x509_certificate
    cert:x509.Certificate = x509.load_pem_x509_certificate(cert_pem.encode('utf-8'))
    
    return False if datetime.datetime.now() > cert.not_valid_before and datetime.datetime.now() < cert.not_valid_after else True

def get_or_renew_and_update_iam_roles_anywhere_certs(cognito_user_name:str, subs_ddb_item:dict) -> Tuple[str, str, str]:
    """
    renews the certificates if needed;  updates the certs in infinstor-subscribers table; also updates the passed subs_ddb_item dict with new certificate values

    _extended_summary_

    Args:
        cognito_user_name (str): _description_
        subs_ddb_item (dict): existing subscriber ddb item with 'customerId', 'productCode', 'iamRolesAnywhereCertArn', 'iamRolesAnywhereCert' and 'iamRolesAnywhereCertPrivateKey' set in it

    Returns:
        Tuple[str, str, str]: returns the tuple cert_private_key, cert_arn, cert
    """
    cert_priv_key:str = subs_ddb_item['iamRolesAnywhereCertPrivateKey']['S'] if subs_ddb_item.get('iamRolesAnywhereCertPrivateKey') else None
    cert:str = subs_ddb_item['iamRolesAnywhereCert']['S'] if subs_ddb_item.get('iamRolesAnywhereCert') else None
    cert_arn:str = subs_ddb_item['iamRolesAnywhereCertArn']['S'] if subs_ddb_item.get('iamRolesAnywhereCertArn') else None
    
    if not cert or _cert_expired(cert):
        cert_priv_key, cert_arn, cert = _generate_certificate(cognito_user_name, subs_ddb_item)
        
        success:bool; err_str_or_items_list:Union[str, list]
        success, err_str_or_items_list = update_subscriber_info(cognito_user_name, subs_ddb_item['customerId']['S'], subs_ddb_item['productCode']['S'], {'iamRolesAnywhereCertPrivateKey':cert_priv_key, 'iamRolesAnywhereCert':cert, 'iamRolesAnywhereCertArn':cert_arn})
        if not success: 
            print(f"Error: unable to update subscriber table: {err_str_or_items_list}")
            return None, None, None
        
        # update the subscriber ddb item.  accommodate the case where these keys were not present in subs_ddb_item dict ( do not use subs_ddb_item['iamRolesAnywhereCertPrivateKey']['S'] ).
        subs_ddb_item['iamRolesAnywhereCertPrivateKey'] = {'S':cert_priv_key}
        subs_ddb_item['iamRolesAnywhereCert'] = {'S': cert }
        subs_ddb_item['iamRolesAnywhereCertArn'] = { 'S':  cert_arn } 
        
    
    return cert_priv_key, cert_arn, cert

def _generate_certificate(cognito_username:str, subs_ddb_item:dict) -> Tuple[str, str, str]:
    """
    _summary_

    _extended_summary_

    Args:
        cognito_username (str): _description_
        subs_ddb_item (dict): _description_

    Returns:
        Tuple[str, str, str]: returns the generated private key, certificate arn and the certificate for the specified cognito_username
    """
    # https://www.misterpki.com/python-csr/ (uses 'cryptography' module; use this; see One Note > Python 2 > Python Cryptography)
    # https://cryptography.io/en/latest/x509/tutorial/ (tutorial to create a CSR and other x509 operations)
    # https://gist.github.com/Zeerg/0b0313d22124d3e8b478 (uses 'PyOpenSSL' module; do not use this; see One Note > Python 2 > Python Cryptography)

    # Generate the RSA private key
    key:RSAPrivateKey = generate_private_key(public_exponent=65537, key_size=2048)
    print(f"key={key}")

    # https://cryptography.io/en/latest/x509/tutorial/ 
    # write the private key out
    key_string_io:io.StringIO = io.StringIO()
    # https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#module-cryptography.hazmat.primitives.asymmetric.rsa
    # encryption_algorithm=serialization.BestAvailableEncryption(b"passphrase")
    key_string_io.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()).decode("utf-8"))  
    print(f"key_string_io.getvalue()={key_string_io.getvalue()}")

    # https://cryptography.io/en/latest/x509/tutorial/ 
    # Generate a CSR
    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        # Provide various details about who we are.
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Jose"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Infinstor"),
        x509.NameAttribute(NameOID.COMMON_NAME, cognito_username), 
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, subs_ddb_item['emailId']['S'])
    ])).add_extension(
        x509.SubjectAlternativeName([
            # Describe what sites we want this certificate for.
            x509.DNSName(cognito_username)
        ]),
        critical=False,
    # Sign the CSR with the private key.
    ).sign(key, hashes.SHA256())
    print(f"csr={csr}")

    # write out the CSR
    csr_bytes_io:io.BytesIO = io.BytesIO()
    csr_bytes_io.write(csr.public_bytes(serialization.Encoding.PEM))
    print(f"csr_bytes_io.getvalue()={csr_bytes_io.getvalue()}")

    sts_client:STSClient = boto3.client("sts")
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sts.html#STS.Client.assume_role
    assume_role_resp:AssumeRoleResponseTypeDef = sts_client.assume_role(RoleSessionName=f"Session-RoleForPrivateCAUserAccess-{cognito_username}", RoleArn=subs_ddb_item['privateCARoleArnForAccessingPrivateCA']['S'], ExternalId=subs_ddb_item['privateCAExternalIDForRoleForAccessingPrivateCA']['S'])
    
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm-pca.html
    pca_client:ACMPCAClient = boto3.client("acm-pca",aws_access_key_id=assume_role_resp['Credentials']['AccessKeyId'], aws_secret_access_key=assume_role_resp['Credentials']['SecretAccessKey'], aws_session_token=assume_role_resp['Credentials']['SessionToken'])
    
    # CertificateAuthorities:
    # - Arn: arn:aws:acm-pca:us-east-1:019944623471:certificate-authority/18cb0690-977e-45e2-92b3-26852dea695e
    #   CertificateAuthorityConfiguration:
    #     KeyAlgorithm: RSA_2048
    #     SigningAlgorithm: SHA256WITHRSA
    #     Subject:
    #       CommonName: Infinstor Private CA
    #       Locality: San Jose
    #       Organization: Infinstor
    #       State: California
    #   CreatedAt: '2023-01-23T00:57:13.334000+05:30'
    #   LastStateChangeAt: '2023-01-23T00:58:23.257000+05:30'
    #   NotAfter: '2033-01-23T00:58:06+05:30'
    #   NotBefore: '2023-01-22T23:58:21+05:30'
    #   OwnerAccount: '019944623471'
    #   RevocationConfiguration:
    #     CrlConfiguration:
    #       Enabled: false
    #   Serial: '44423515497616197961984279020579877361'
    #   Status: ACTIVE
    #   Type: ROOT    
    # 
    # get the ARN for the private CA using the name "Infinstor Private CA"
    ca_list:ListCertificateAuthoritiesResponseTypeDef = pca_client.list_certificate_authorities()
    ca:CertificateAuthorityTypeDef
    for ca in ca_list['CertificateAuthorities']:
        ca_config:CertificateAuthorityConfigurationTypeDef = ca['CertificateAuthorityConfiguration']
        if ca_config['Subject']['CommonName'].lower() == "Infinstor Private CA".lower(): 
            cwSearch_pca_arn:str = ca['Arn']
            
    # aws acm-pca issue-certificate --certificate-authority-arn "arn:aws:acm-pca:us-east-1:019944623471:certificate-authority/18cb0690-977e-45e2-92b3-26852dea695e" --csr fileb://onpremsrv-csr-certificate_signing_request.pem --signing-algorithm "SHA256WITHRSA" --validity Value=7,Type="DAYS"
    # 
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm-pca.html#ACMPCA.Client.issue_certificate
    #
    # issue_certificate(*, CertificateAuthorityArn: str, Csr: str | bytes | IO | StreamingBody, SigningAlgorithm: SigningAlgorithmType, Validity: ValidityTypeDef, ApiPassthrough: ApiPassthroughTypeDef = ..., TemplateArn: str = ..., ValidityNotBefore: ValidityTypeDef = ..., IdempotencyToken: str = ...) -> IssueCertificateResponseTypeDef
    # ValidityTypeDef(Value=7, Type="DAYS")
    # TemplateArn (string) -- Specifies a custom configuration template to use when issuing a certificate. If this parameter is not provided, Amazon Web Services Private CA defaults to the EndEntityCertificate/V1 template
    issue_cert_resp:IssueCertificateResponseTypeDef = pca_client.issue_certificate(CertificateAuthorityArn=cwSearch_pca_arn, Csr=csr_bytes_io.getvalue(), SigningAlgorithm="SHA256WITHRSA", Validity={'Type':'DAYS', 'Value':7})
    # response has the keys: CertificateArn and ResponseMetadata
    print(f"issue_cert_resp={issue_cert_resp}")

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm-pca.html#ACMPCA.Waiter.CertificateIssued
    waiter:CertificateIssuedWaiter = pca_client.get_waiter('certificate_issued')
    # Polls ACMPCA.Client.get_certificate() every 3 seconds until a successful state is reached. An error is returned after 60 failed checks.
    waiter.wait(CertificateAuthorityArn=cwSearch_pca_arn,   CertificateArn=issue_cert_resp["CertificateArn"])
    print("Waiter finished waiting for certificate issuance")

    # get the certificate.
    # May see this error: RequestInProgressException: An error occurred (RequestInProgressException) when calling the GetCertificate operation: The request to issue certificate arn:aws:acm-pca:us-east-1:019944623471:certificate-authority/18cb0690-977e-45e2-92b3-26852dea695e/certificate/20105475bd547e7d92dcb7abc30a4647 is still in progress. Try again later.
    # 
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm-pca.html#ACMPCA.Client.get_certificate
    get_cert_resp:GetCertificateResponseTypeDef = pca_client.get_certificate(CertificateAuthorityArn=cwSearch_pca_arn, CertificateArn=issue_cert_resp["CertificateArn"])
    # response has the keys: "Certificate", "CertificateChain", "ResponseMetadata"
    print(f"get_cert_resp={get_cert_resp}")
    # decode the "\n" in the certificate to actual new lines
    cert_decoded = get_cert_resp['Certificate'].encode('utf-8').decode('unicode_escape')
    print(f"get_cert_resp['certificate'].decode_as_unicode_escape={cert_decoded}")
    
    return key_string_io.getvalue(), issue_cert_resp["CertificateArn"], cert_decoded
    
def filter_empty_in_dict_list_scalar(dict_list_scalar:Union[list, dict, Any]) -> Union[list, dict, Any]:
    """
    given a 'dict' or 'list' as input, removes all elements in these containers that are empty: scalars with None, strings that are '', lists and dicts that are empty.  Note that the filtering is in-place: modifies the passed list or dict

    Args:
        dict_list_scalar (Union[list, dict, Any]): see above
    """
    try:
        # depth first traveral
        if isinstance(dict_list_scalar, dict):
            keys_to_del:list = []
            for k in dict_list_scalar.keys():  
                filter_empty_in_dict_list_scalar(dict_list_scalar[k])
                
                # check if the 'key' is now None or empty.  If so, remove the 'key'
                if not dict_list_scalar[k]: 
                    # cannont do dict.pop(): RuntimeError: dictionary changed size during iteration
                    # dict_list_scalar.pop(k)
                    keys_to_del.append(k)
            
            # now delete the keys from the map
            for k in keys_to_del:
                dict_list_scalar.pop(k)
            
            return dict_list_scalar
        elif isinstance(dict_list_scalar, list):
            i = 0; length = len(dict_list_scalar)
            while i < length: 
                filter_empty_in_dict_list_scalar(dict_list_scalar[i])
            
                # check if element is now None (if scalar) or empty (if list or dict).  If so, remove the element from the list
                if not dict_list_scalar[i]:
                    dict_list_scalar.remove(dict_list_scalar[i])
                    i -= 1; length -= 1
                
                i += 1
            return dict_list_scalar
        else: # this must be a non container, like int, str, datatime.datetime
            return dict_list_scalar
    except Exception as e:
        # some excpetion, just log it..
        print(f"_filter_empty_in_dict_list_scalar(): Caught exception: {e}")
        traceback.print_exc()
        
        return None
