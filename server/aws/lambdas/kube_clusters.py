import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from utils import get_cognito_user

KUBE_CLUSTERS_TABLE = os.environ['KUBE_CLUSTERS_TABLE']

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


def add_kube_cluster(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    body = event['body']
    item = json.loads(body)

    cluster_name = item['cluster_name']
    namespace = item['namespace']
    cluster_type = item['cluster_type']
    if cluster_type == 'GKE':
        record = {
            'username': {'S': cognito_username},
            'cluster_name': {'S': cluster_name},
            'namespace': {'S': namespace},
            'cluster_type': {'S': cluster_type},
            'gke_location_type': {'S': item['gke_location_type']},
            'gke_location': {'S': item['gke_location']},
            'gke_creds': {'S': item['gke_creds']},
            'gke_project': {'S': item['gke_project']}
        }
    elif cluster_type == 'EKS':
        role = item['role']
        role_ext = item['role_ext']
        region = item['region']
        record = {
            'username': {'S': cognito_username},
            'cluster_name': {'S': cluster_name},
            'namespace': {'S': namespace},
            'cluster_type': {'S': cluster_type},
            'eks_role': {'S': role},
            'eks_role_ext': {'S': role_ext},
            'eks_region': {'S': region}
        }
    else:
        return respond("Invalid Cluster Type", dict())

    ddb_client = boto3.client('dynamodb')
    try:
        ddb_client.put_item(TableName=KUBE_CLUSTERS_TABLE, Item=record)
    except Exception as ex:
        logger.warning("Failed to add cluster: " + str(ex))
        return respond("Failed to add cluster", dict())

    return respond(None, dict())


def remove_kube_cluster(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    body = event['body']
    item = json.loads(body)

    cluster_name = item['cluster_name']
    ddb_client = boto3.client('dynamodb')

    key = {
        'username': {'S': cognito_username},
        'cluster_name': {'S': cluster_name}
    }
    try:
        ddb_client.delete_item(TableName=KUBE_CLUSTERS_TABLE, Key=key)
    except Exception as ex:
        logger.warning("remove_kube_cluster failed: " + str(ex))
        return respond("Remove failed", dict())

    return respond(None, dict())


def query_kube_clusters(cognito_username):

    ddb_client = boto3.client('dynamodb')

    try:
        response = ddb_client.query(TableName=KUBE_CLUSTERS_TABLE,
                     KeyConditionExpression='username = :un',
                     ExpressionAttributeValues={':un': {'S': cognito_username}})
    except Exception as ex:
        logger.warning("Kube cluster query failed: " + str(ex))
        return []

    cluster_list = []
    if 'Items' in response:
        for item in response['Items']:
            c_info = {
                'cluster_name': item['cluster_name']['S'],
                'namespace' : item['namespace']['S'],
                'cluster_type': item['cluster_type']['S']
            }
            if c_info['cluster_type'] == 'GKE':
                c_info['gke_location_type'] = item['gke_location_type']['S']
                c_info['gke_location'] = item['gke_location']['S']
                c_info['gke_creds'] = item['gke_creds']['S']
                c_info['gke_project'] = item['gke_project']['S']
            elif c_info['cluster_type'] == 'EKS':
                c_info['eks_role'] = item['eks_role']['S']
                c_info['eks_role_ext'] = item['eks_role_ext']['S']
                c_info['eks_region'] = item['eks_region']['S']
            else:
                logger.warning("Invalid cluster definition")
                ##Ignore this record
                continue
            cluster_list.append(c_info)
    return cluster_list


def get_kube_clusters(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    cluster_list = query_kube_clusters(cognito_username)

    if cluster_list:
        return respond(None, {'kube_clusters': cluster_list})
    else:
        return respond(None, dict())

