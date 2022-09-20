import boto3
from typing import TYPE_CHECKING, Tuple
if TYPE_CHECKING:
  from mypy_boto3_cognito_idp import CognitoIdentityProviderClient
else:
  CognitoIdentityProviderClient = object
import cfnresponse
import uuid
import string
import secrets
import traceback

# pylint: disable=bad-indentation,broad-except

def create_cognito_user(event):
    user_pool_id = event['ResourceProperties']['user_pool_id']
    print('user_pool_id=' + str(user_pool_id))
    web_client_id = event['ResourceProperties']['web_client_id']
    print('web_client_id=' + str(web_client_id))
    root_user_email = event['ResourceProperties']['root_user_email']
    print('root_user_email=' + str(root_user_email))
    service = event['ResourceProperties']['MlflowParallelsDomain']
    print('service=' + str(service))
      
    root_user_password = (''.join(secrets.choice(string.ascii_lowercase) for i in range(8))) + (''.join(secrets.choice(string.digits) for i in range(8)))+ (''.join(secrets.choice(string.ascii_uppercase) for i in range(8)))+ (''.join(secrets.choice('^$*.[]{}()?"!@#%&/\,><:;|_~`') for i in range(8)))
    cog:CognitoIdentityProviderClient = boto3.client('cognito-idp')
      # create root user
    try:
      resp = cog.sign_up(ClientId=web_client_id, Username='root', Password=root_user_password,
          UserAttributes=[{'Name': 'email', 'Value': root_user_email}, {'Name': 'custom:serviceName', 'Value': service}])
    except Exception:
        print('Exception while creating root user in cognito: ', traceback.format_exc())

def ddb_update_sub_table_for_root_user(event, subscribers_table_name, customer_id=None):
    root_user_email = event['ResourceProperties']['root_user_email']
    print('root_user_email=' + str(root_user_email))
    customer_id = customer_id if customer_id else str(uuid.uuid4())
    print('customer_id=' + str(customer_id))
    product_code = '9fcazc4rbiwp6ewg4xlt5c8fu'
    subs = 'SUBSCRIPTION_ENTITLED'
    eksRegion = event['ResourceProperties']['eksRegion']
    eksRoleArn = event['ResourceProperties']['eksRoleArn']
      # IAM Role's external ID
    eksRoleExtId = event['ResourceProperties']['eksRoleExtId']
    ecrType = event['ResourceProperties']['ecrType']
    ecrRegion = event['ResourceProperties']['ecrRegion']
    ecrRole = event['ResourceProperties']['ecrRole']
    ecrRoleExt = event['ResourceProperties']['ecrRoleExt']
    gke_location_type = event['ResourceProperties']['GkeLocationType']
    gke_location = event['ResourceProperties']['GkeLocation']
    gke_credentials = event['ResourceProperties']['GkeCredentials']
    gke_project = event['ResourceProperties']['GkeProject']
    additionalImports = event['ResourceProperties']['AdditionalImports']
    additionalPackages = event['ResourceProperties']['AdditionalPackages']
      
    ean = {
              '#SU':                'subs',
              '#EM':                'emailId',
              '#UN':                'userName',
              '#EKSREGION':         'eksRegion',
              '#EKSROLEARN':        'eksRole',
              '#EKSROLEEXTID':      'eksRoleExt',
              '#ecrType':           'ecrType',
              '#ecrRegion':         'ecrRegion',
              '#ecrRole':           'ecrRole',
              '#ecrRoleExt':        'ecrRoleExt',
              '#gke_location_type': 'gke_location_type',
              '#gke_location':      'gke_location',
              '#gke_creds':         'gke_creds',
              '#gke_project':       'gke_project',
              '#additionalImports': 'additionalImports',
              '#additionalPackages':'additionalPackages'              
            }
    eav = {
              ':su'                : {'S': subs},
              ':em'                : {'S': root_user_email},
              ':un'                : {'S': 'root'},
              ':eksregion'         : {'S': eksRegion},
              ':eksrolearn'        : {'S': eksRoleArn},
              ':eksroleextid'      : {'S': eksRoleExtId},
              ':ecrType'           : {'S': ecrType},
              ':ecrRegion'         : {'S': ecrRegion},
              ':ecrRole'           : {'S': ecrRole},
              ':ecrRoleExt'        : {'S': ecrRoleExt},
              ':gke_location_type' : {'S': gke_location_type},
              ':gke_location'      : {'S': gke_location},
              ':gke_creds'         : {'S': gke_credentials},
              ':gke_project'       : {'S': gke_project},
              ':additionalImports' : {'S': additionalImports},
              ':additionalPackages': {'S': additionalPackages}
            }
    ue = 'SET #SU = :su, #EM = :em, #UN = :un, #EKSREGION = :eksregion, #EKSROLEARN = :eksrolearn, #EKSROLEEXTID = :eksroleextid, #ecrType = :ecrType, #ecrRegion = :ecrRegion, #ecrRole = :ecrRole, #ecrRoleExt = :ecrRoleExt, #gke_location_type = :gke_location_type, #gke_location = :gke_location, #gke_creds = :gke_creds, #gke_project = :gke_project, #additionalImports = :additionalImports, #additionalPackages = :additionalPackages'

    ddbc = boto3.client('dynamodb')
      # Edits an existing item's attributes, or adds a new item to the table if it does not already exist.
    ddbc.update_item(
                  TableName=subscribers_table_name,
                  ExpressionAttributeNames = ean,
                  ExpressionAttributeValues = eav,
                  UpdateExpression=ue,
                  Key={'customerId': { 'S': customer_id }, 'productCode': { 'S': product_code }},
                  ReturnValues='NONE')
                
def find_customer_id_for_root(subscribers_table_name:str) -> Tuple[str, dict]:
    # for update first determine the customerId for the root user
    ddbc = boto3.client('dynamodb')
    resp = ddbc.scan(TableName=subscribers_table_name, Select='ALL_ATTRIBUTES')
    customer_id = None
    if 'Items' in resp:
        items = resp['Items']
        for itm in items:
            if (itm['userName']['S'] == 'root'):
                customer_id = itm['customerId']['S']
                break
    if (customer_id == None):
      print('Error: Could not find customerId for root user')
      return None, { 'Data':'Error: Could not find customerId for root user' }
    
    return customer_id, None
  
def crud_cognito_and_sub_ddb(event, request_type) -> dict:
    """
    creates 'root' user in cognito and sets up 'subscribers' table

    _extended_summary_

    Args:
        event (dict): event for the lambda
        request_type (str): 'create' or 'update' or 'delete'

    Returns:
        dict: None if successful.  A dict with error message on failure to be used by cfnresponse
    """
    subscribers_table_name = event['ResourceProperties']['subscribers_table_name']
    mlflowServerType:str = event['ResourceProperties']['MlflowServerType']
    print(f'subscribers_table_name={subscribers_table_name}; mlflowServerType={mlflowServerType}')
    
    # in case of an update behavior using create, delete, create is called with the new resource's properties.
    if request_type == 'Create':
      if not mlflowServerType == 'infinstor': 
        print(f"ServerType={mlflowServerType}: creating 'root' user in cognito")
        create_cognito_user(event)
      else:
        print(f"ServerType={mlflowServerType}: not creating 'root' user in cognito")

      if mlflowServerType == 'infinstor': 
        print(f"ServerType={mlflowServerType}: updating 'root' user in subscribers table")
        customer_id:str; err:dict
        customer_id, err = find_customer_id_for_root(subscribers_table_name)
        if err: return err
        
        ddb_update_sub_table_for_root_user(event, subscribers_table_name, customer_id=customer_id)
      else:
        print(f"ServerType={mlflowServerType}: creating 'root' user in subscribers table")
        ddb_update_sub_table_for_root_user(event, subscribers_table_name)
                  
      # Everything OK... send the signal back
      print('Create Operation successful!')
      return None
    # for update we get 'ResourceProperties' (which has the new resource's properties) and 'OldResourceProperties' key (has the old resources properties)
    elif request_type == 'Update':
      print(f"ServerType={mlflowServerType}: updating 'root' user in subscribers table")
      customer_id:str; err:dict
      customer_id, err = find_customer_id_for_root(subscribers_table_name)
      if err: return err
      
      # for update we get 'ResourceProperties' (which has the new resource's properties). 'OldResourceProperties' key (has the old resources properties) is also availble
      ddb_update_sub_table_for_root_user(event, subscribers_table_name, customer_id=customer_id)

      # Everything OK... send the signal back
      print('Update Operation successful!')
      return None
    # for delete we get 'ResourceProperties' key (which has the old resource's properties)
    elif request_type == 'Delete':
      ### for delete we get 'ResourceProperties' key (which has the old resource's properties).  So for a create/delete update behavior, the new properties added to the custom resource will not be available in event['ResourceProperites'].  See IN-743
      # first delete cognito user named root if this is not using external auth
      if not mlflowServerType == 'infinstor':
        print(f"ServerType={mlflowServerType}: deleting root user in cognito")
        cog = boto3.client('cognito-idp')
        user_pool_id = event['ResourceProperties']['user_pool_id']
        try:
          cog.admin_delete_user(UserPoolId=user_pool_id, Username='root')
        except Exception:
          print('Exception while deleting root. Ignoring', traceback.format_exc())
        
        # second remove root entry from ddb
        try:
          print(f"ServerType={mlflowServerType}: deleting all items in subscriber table")
          ddbc = boto3.client('dynamodb')
          resp = ddbc.scan(TableName=subscribers_table_name)
          items = resp['Items']
          customerIds = []
          for item in items:
            # single tenant has single subscriber, so adding all to be deleted..
            customerIds.append(item['customerId']['S'])
          print(f'Deleting {customerIds} from subscribers table')
          product_code = '9fcazc4rbiwp6ewg4xlt5c8fu'
          for customer_id in customerIds:
            ddbc.delete_item(
                    TableName=subscribers_table_name,
                    Key={'customerId': { 'S': customer_id }, 'productCode': { 'S': product_code }})
        except Exception:
          print('Caught exception while deleting parallels-Subscribers entries: ', traceback.format_exc())
      else:
        # TODO: ideally we should be removing the attributes from the subscriber item/row we added for this case
        print(f"ServerType={mlflowServerType}: not deleting 'root' user in cognito and not deleting 'root' user in {subscribers_table_name} table")

      # Everything OK... send the signal back
      print('Delete Operation successful!')
      return None

def handler(event, context):
  print(f'event={event}')
  print(f'context={context}')
  
  # for create we get 'ResourceProperites' key (which has the new resource's properites)
  # for update we get 'ResourceProperties' (which has the new resource's properties) and 'OldResourceProperties' key (has the old resources properties)
  # for delete we get 'ResourceProperties' key (which has the old resource's properties)
  try:
    # Init ...
    request_type = event['RequestType']
    service = event['ResourceProperties']['MlflowParallelsDomain']
    print('service=' + str(service))
    
    response_data = crud_cognito_and_sub_ddb(event, request_type)
    cfnresponse.send(event, context, cfnresponse.SUCCESS if not response_data else cfnresponse.FAILED, {} if not response_data else response_data, physicalResourceId=service)
  except Exception as e:
    print('Exception caught: Operation failed: ', traceback.format_exc())    
    # {
    # "Status": "FAILED",
    # "Reason": "See the details in CloudWatch Log Stream: 2022/08/11/[$LATEST]44e401a87d3d4fa2a87639d8655e66fe",
    # "PhysicalResourceId": "isstage23.isstage1.com",
    # "StackId": "arn:aws:cloudformation:us-east-1:076307257577:stack/single-tenant-cft-20220811-1/0dcfbaa0-19a1-11ed-8214-0a53a9242735",
    # "RequestId": "8830b0f5-64d9-4739-a275-025f231ed13c",
    # "LogicalResourceId": "SingleTenantCustomResource",
    # "NoEcho": false,
    # "Data": {}
    # }
    cfnresponse.send(event, context, cfnresponse.FAILED, {'Data': str(e)}, physicalResourceId=service)
