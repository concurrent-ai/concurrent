
import json
import os

from parallels_version import get_version

def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': str(err) if err else res,
        'headers': {
            'Content-Type': 'text/plain',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*',
            'Access-Control-Allow-Credentials': '*'
        },
    }


def cliclient_authorize(event, context):
    print('## ENVIRONMENT VARIABLES')
    print(os.environ)
    print('## EVENT')
    print(event)

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))
        
    qs = event['queryStringParameters']
    print(f"event['queryStringParameters']={event['queryStringParameters']}")

    msg = "Error: 'code' not found"
    code = qs.get("code", None)
    if code: msg = f"{code}\nCopy above code and paste it into the command line login client"
        
    return respond(None, msg)

