import json
import os

from parallels_version import get_version
from utils import get_service_conf, cognito_callback_url, cognito_domain, check_if_external_oauth

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


def getversion(event, context):
    print('## ENVIRONMENT VARIABLES')
    print(os.environ)
    print('## EVENT')
    print(event)

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    success, status, conf = get_service_conf()
    if (success == False):
        print('getversion: Error ' + status + ' lookup service conf')
        return respond(ValueError('Could not get service config'))

    #        runProjectLambda  : 'arn:aws:lambda:xxx'
    #         configVersion    : 1
    # cognitoMlflowuiClientId  : '6plr4xxxxx'
    #             serviceHost  : 'xxxx.concurrent-ai.org'
    #         cognitoUserPool  : 'us-east-1_xxxxx'
    #     cognitoCliClientId   : '1pcfrh7xxxxx'
    #     mlflowParallelsApiId : 'wncxxxxx'
    #             isStaging    : 'true'
    # mlflowParallelsUiDnsName : 'mlflowui'
    #     periodRunLambdaArn   : 'arn:aws:lambda:xxxxx'
    # mlflowParallelsDnsName   : 'concurrent'
    #         cognitoClientId  : '1pcfrhxxxxx'
    #             cookieHost   : 'concurrent-ai.org'
    #         executeDagLambda : 'arn:aws:lambda:us-east-1:xxxxx'
    rv = dict()
    rv['version'] = get_version()
    rv['cognitoClientId'] = conf['cognitoClientId']['S']
    rv['region'] = os.environ['AWS_REGION']
    rv['cognitoCallbackUrl'] = cognito_callback_url(conf)
    rv['cognitoDomain'] = cognito_domain(conf)
    rv['isExternalAuth'] = check_if_external_oauth()
    rv['mlflowParallelsDnsName'] = conf['mlflowParallelsDnsName']['S']
    rv['mlflowParallelsUiDnsName'] = conf['mlflowParallelsUiDnsName']['S']
    rv['cookieHost'] = conf['cookieHost']['S']
    rv['cognitoMlflowuiClientId'] = conf['cognitoMlflowuiClientId']['S']
    print('getversion returning ' + str(rv))
    return respond(None, rv)
