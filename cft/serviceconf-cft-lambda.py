import boto3
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import UpdateItemOutputTypeDef
else:
    DynamoDBClient = object
    UpdateItemOutputTypeDef = object
import cfnresponse

def handler(event, context):
    print(f'event={event}')
    print(f'context={context}')
    
    # initialized outside the 'try' block as used as the physicalResourceId in cfnresponse.send()
    serviceConfTable = event['ResourceProperties']['ServiceConfTable']
    try:
        ddb_client:DynamoDBClient = boto3.client('dynamodb')    
        
        reqType:str = event['RequestType']
        if  reqType == "Create" or reqType == "Update":
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.update_item
            # Edits an existing item's attributes, or adds a new item to the table if it does not already exist. You can put, delete, or add attribute values. You can also perform a conditional update on an existing item (insert a new attribute name-value pair if it doesn't exist, or replace an existing name-value pair if it has certain expected attribute values).
            #
            # do not use put_item() since it replaces and doesn't udpate.
            ean = {
                #'#configVersion': 'configVersion', 
                '#cognitoUserPool' : 'cognitoUserPool',
                '#cognitoClientId' : 'cognitoClientId',
                '#cognitoCliClientId' : 'cognitoCliClientId',
                '#cognitoMlflowuiClientId' : 'cognitoMlflowuiClientId',
                '#isStaging' : 'isStaging',
                '#cookieHost' : 'cookieHost',
                '#serviceHost' : 'serviceHost',
                '#periodRunLambdaArn' : 'periodRunLambdaArn',
                '#runProjectLambda' : 'runProjectLambda',
                '#executeDagLambda' : 'executeDagLambda',
                '#mlflowParallelsApiId' : 'mlflowParallelsApiId',
                '#mlflowParallelsDnsName' : 'mlflowParallelsDnsName',
                '#mlflowParallelsUiDnsName' : 'mlflowParallelsUiDnsName'
            }

            eav = {
                #':configVersion': { 'N': 1 }, 
                ':cognitoUserPool' : { 'S': event['ResourceProperties']['CognitoUserPoolId'] },
                ':cognitoClientId' : { 'S': event['ResourceProperties']['CliClientId'] },
                ':cognitoCliClientId' : { 'S': event['ResourceProperties']['CliClientId'] },
                ':cognitoMlflowuiClientId' : { 'S': event['ResourceProperties']['MlflowuiClientId'] },
                ':isStaging' : { 'S': 'true' },
                ':cookieHost' : { 'S': event['ResourceProperties']['MlflowParallelsDomain'] },
                ':serviceHost' : { 'S': event['ResourceProperties']['MlflowParallelsDomain'] },
                ':periodRunLambdaArn' : { 'S': event['ResourceProperties']['periodRunLambdaArn'] },
                ':runProjectLambda' : { 'S': event['ResourceProperties']['runProjectLambdaArn'] },
                ':executeDagLambda' : { 'S': event['ResourceProperties']['executeDagLambdaArn'] },
                ':mlflowParallelsApiId' : { 'S': event['ResourceProperties']['MlflowParallelsApiId'] },
                ':mlflowParallelsDnsName' : { 'S': event['ResourceProperties']['MlflowParallelsDnsName'] },
                ':mlflowParallelsUiDnsName' : { 'S': event['ResourceProperties']['MlflowParallelsUiDnsName'] }
            }
            
            print(f'eav={eav}')
            print(f'serviceConfTable={serviceConfTable}')

            update_item_retval:UpdateItemOutputTypeDef = ddb_client.update_item(
                ExpressionAttributeNames=ean, ExpressionAttributeValues=eav, Key={ 'configVersion': { 'N': '1' } }, 
                ReturnValues='ALL_NEW', TableName=serviceConfTable, 
                UpdateExpression="SET #cognitoUserPool = :cognitoUserPool, #cognitoClientId = :cognitoClientId, #cognitoCliClientId = :cognitoCliClientId, #cognitoMlflowuiClientId = :cognitoMlflowuiClientId,  #isStaging = :isStaging, #cookieHost = :cookieHost, #serviceHost = :serviceHost, #periodRunLambdaArn = :periodRunLambdaArn, #runProjectLambda = :runProjectLambda, #executeDagLambda = :executeDagLambda, #mlflowParallelsApiId = :mlflowParallelsApiId, #mlflowParallelsDnsName = :mlflowParallelsDnsName, #mlflowParallelsUiDnsName = :mlflowParallelsUiDnsName")
            
            print(f'update_item_retval={update_item_retval}')
            
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=serviceConfTable)
        elif reqType == 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=serviceConfTable)
        else:
            cfnresponse.send(event, context, cfnresponse.FAILED, {'Data':f'unknown requestType={reqType}'}, physicalResourceId=serviceConfTable)
    except Exception as e:
        print('Operation failed...')
        print(str(e))
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Data':str(e)}, physicalResourceId=serviceConfTable)
    
if __name__ == '__main__':
    event = { 
                'RequestType': 'Create',
                'ResourceProperties': {
                    'ServiceConfTable': 'infinstor-ServiceConf',
                    'CognitoUserPoolId': 'us-east-1_WKUzeIsBB',
                    'CliClientId': '539nr0j3b3u01ml40e8vdma3cr',
                    'MlflowuiClientId': '5n7fdneen62e4g1gsqm176hp5v',
                    'MlflowParallelsDomain': 'isstage23.isstage1.com',
                    'periodRunLambdaArn':'arn:aws:lambda:us-east-1:076307257577:function:parallels-lambda-20220831-2-MLflowParall-periodrun-t6sy4mdSjH2C',
                    'runProjectLambdaArn':'arn:aws:lambda:us-east-1:076307257577:function:parallels-lambda-20220831-2-MLflowParal-runproject-1eTpUEpkfmLw',
                    'MlflowParallelsApiId':'gxcgw45ng3',
                    'MlflowParallelsDnsName':'parallels',
                    'MlflowParallelsUiDnsName':'mlflowui23'
                }
                
            }
    handler(event, None)

# const docClient = new AWS.DynamoDB.DocumentClient();
# exports.handler = function(event, context) {
#   console.log(JSON.stringify(event, null, 2));
#   var tableName = event.ResourceProperties.DynamoTableName;
#   if (event.RequestType == "Create" || event.RequestType == "Update") {
#     var item = {};
#     item['configVersion'] = 1;
#     item['cognitoUserPool'] = event.ResourceProperties.CognitoUserPoolId;
#     item['cognitoClientId'] = event.ResourceProperties.CliClientId;
#     item['cognitoCliClientId'] = event.ResourceProperties.CliClientId;
#     item['cognitoMlflowuiClientId'] = event.ResourceProperties.MlflowuiClientId;
#     item['isStaging'] = "true";
#     item['cookieHost'] = event.ResourceProperties.MlflowParallelsDomain;
#     item['serviceHost'] = 'service.' + event.ResourceProperties.MlflowParallelsDomain;
#     item['periodRunLambdaArn'] = event.ResourceProperties.periodrun;
#     item['runProjectLambda'] = event.ResourceProperties.runproject;
#     item['mlflowParallelsApiId'] = event.ResourceProperties.MlflowParallelsApiId;
#     item['mlflowParallelsDnsName'] = event.ResourceProperties.MlflowParallelsDnsName;
#     item['MlflowParallelsUiDnsName'] = event.ResourceProperties.MlflowParallelsUiDnsName;
#     console.log("item:", item);
#     var params = {
#       TableName: tableName,
#       Item: item
#     };
#     console.log("Creating or Updating configVersion 1");
#     // do not use put() since it replaces and does not update.  Need to update() since there is no guarantee that single tenant stack will run during a CFT update (no CFT update performed if there is no change to the CFT parameters or CFT resources)
#     // https://docs.aws.amazon.com/AWSJavaScriptSDK/latest/AWS/DynamoDB/DocumentClient.html#update-property
#     docClient.put(params, function(err, data) {                
#       if (err) {
#         console.log('error creating/updating document', err);
#         response.send(event, context, "FAILED", {}, tableName + '_' + item['configVersion']);
#       } else {
#         response.send(event, context, "SUCCESS", {}, tableName + '_' + item['configVersion']);
#       }
#     });
#   } else if (event.RequestType == "Delete") {
#     response.send(event, context, "SUCCESS", {});
#   } else {
#     response.send(event, context, "FAILED", 'Unknown request type');
#   }
# };
