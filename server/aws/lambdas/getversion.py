import json
import os

from parallels_version import get_version
from utils import get_service_conf, cognito_callback_url, cognito_domain

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

    rv = dict()
    rv['version'] = get_version()
    rv['cognitoClientId'] = conf['cognitoClientId']['S']
    rv['region'] = os.environ['AWS_REGION']
    rv['cognitoCallbackUrl'] = cognito_callback_url(conf)
    rv['cognitoDomain'] = cognito_domain(conf)
    rv['isExternalAuth'] = conf['isExternalAuth']['S'] == 'true' if conf.get('isExternalAuth', False) else False
    print('getversion returning ' + str(rv))
    return respond(None, rv)
