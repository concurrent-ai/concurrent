import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from utils import get_cognito_user, is_user_admin, get_subscriber_name

#KUBE_CLUSTERS_TABLE = os.environ['KUBE_CLUSTERS_TABLE']
KUBE_CLUSTERS_TABLE = "concurrent-k8s-clusters"

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


def get_cluster_access_range_key(principal_type, principal, cluster_name, namespace):
    if principal_type == 'group':
        key = 'g/' + principal + '/' + cluster_name + '/' + namespace
    elif principal_type == 'user':
        key = 'u/' + principal + '/' + cluster_name + '/' + namespace
    else:
        raise Exception('Invalid principal type: ' + principal_type)
    return key


def get_cluster_access_range_key_prefix(principal_type, principal):
    if principal_type == 'group':
        key = 'g/' + principal + '/'
    elif principal_type == 'user':
        key = 'u/' + principal + '/'
    else:
        raise Exception('Invalid principal type: ' + principal_type)
    return key


def get_cluster_info_range_key(cluster_name, namespace, owner):
    return owner + '/' + cluster_name + '/' + namespace


def get_cluster_info_range_key_prefix(owner):
    return owner + '/'


def get_cluster_info_hash_key():
    return 'clusterinfo'


def get_cluster_access_hash_key():
    return 'clusteraccess'


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

    is_admin = is_user_admin(cognito_username)

    body = event['body']
    item = json.loads(body)

    cluster_name = item['cluster_name']
    namespace = item['namespace']
    cluster_type = item['cluster_type']

    hash_key = get_cluster_info_hash_key()

    if is_admin:
        owner = get_subscriber_name(cognito_username)
    else:
        owner = cognito_username

    range_key = get_cluster_info_range_key(cluster_name, namespace, owner)

    if cluster_type == 'GKE':
        record = {
            'hash_key': {'S': hash_key},
            'range_key': {'S': range_key},
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
        ecr_role = item['ecr_role']
        ecr_role_ext = item['ecr_role_ext']
        ecr_type = item['ecr_type']
        ecr_region = item['ecr_region']
        record = {
            'hash_key': {'S': hash_key},
            'range_key': {'S': range_key},
            'cluster_type': {'S': cluster_type},
            'eks_role': {'S': role},
            'eks_role_ext': {'S': role_ext},
            'eks_region': {'S': region},
            'ecr_role': {'S': ecr_role},
            'ecr_role_ext': {'S': ecr_role_ext},
            'ecr_type': {'S': ecr_type},
            'ecr_region': {'S': ecr_region}
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


def query_cluster_access_records(principal_type):
    hash_key = get_cluster_access_hash_key()
    if principal_type == 'user':
        range_key_prefix = 'u/'
    else:
        range_key_prefix = 'g/'
    ddb_client = boto3.client('dynamodb')
    eav = {
        ':hk' : {'S': hash_key},
        ':rk' : {'S': range_key_prefix}
    }

    cluster_access_records = []
    try:
        response = ddb_client.query(TableName=KUBE_CLUSTERS_TABLE,
                    KeyConditionExpression='hash_key = :hk AND begins_with(range_key, :rk)',
                    ExpressionAttributeValues=eav)
    except Exception as ex:
        logger.warning("Kube cluster query failed: " + str(ex))
        return []

    if 'Items' in response:
        for item in response['Items']:
            principal_type, principal, cluster_name, namespace = parse_access_range_key(item['range_key']['S'])
            cluster_access_records.append((principal_type, principal, cluster_name, namespace))

    return cluster_access_records


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

    is_admin = is_user_admin(cognito_username)

    if is_admin:
        if 'owner' in item:
            owner = item['owner']
        else:
            owner = get_subscriber_name(cognito_username)
    else:
        owner = cognito_username

    cluster_name = item['cluster_name']
    namespace = item['namespace']

    ## Delete
    delete_txns = []
    hash_key = get_cluster_info_hash_key()
    range_key = get_cluster_info_range_key(cluster_name, namespace, owner)
    delete_cluster_info_txn = {
        'Delete' : {
            'TableName': KUBE_CLUSTERS_TABLE,
            'Key': {
                'hash_key': {'S': hash_key},
                'range_key': {'S': range_key}
            }
        }
    }
    delete_txns.append(delete_cluster_info_txn)

    ## Fetch cluster access records
    user_access_records = query_cluster_access_records('user')
    for principal_type, principal, cl_name, ns in user_access_records:
        if cluster_name == cl_name and namespace == ns:
            delete_access_txn = {
                'Delete':  {
                    'TableName': KUBE_CLUSTERS_TABLE,
                    'Key': {
                        'hash_key' : {'S': get_cluster_access_hash_key()},
                        'range_key' : {'S': get_cluster_access_range_key(principal_type, principal, cl_name, ns)}
                    }
                }
            }
            delete_txns.append(delete_access_txn)
    group_access_records = query_cluster_access_records('group')
    for principal_type, principal, cl_name, ns in group_access_records:
        if cluster_name == cl_name and namespace == ns:
            delete_access_txn = {
                'Delete': {
                    'TableName': KUBE_CLUSTERS_TABLE,
                    'Key': {
                        'hash_key' : {'S': get_cluster_access_hash_key()},
                        'range_key' : {'S': get_cluster_access_range_key(principal_type, principal, cl_name, ns)}
                    }
                }
            }
            delete_txns.append(delete_access_txn)

    print(delete_txns)
    ddb_client = boto3.client('dynamodb')
    for i in range(len(delete_txns) // 100 + 1):
        txns_to_delete = delete_txns[100*i: min(len(delete_txns), 100*(i+1))]
        try:
            ddb_client.transact_write_items(TransactItems=txns_to_delete)
        except Exception as ex:
            logger.warning("remove_kube_cluster failed: " + str(ex))
            return respond("Remove failed", dict())

    return respond(None, dict())


def parse_access_range_key(range_key):
    fields = range_key.split('/')
    if fields[0] == 'u':
        principal_type = 'user'
    else:
        principal_type = 'group'
    return principal_type, fields[1], fields[2], fields[3]


def get_cluster_name_from_info_range_key(range_key):
    owner, cluster_name, namespace = range_key.split('/')
    return owner, cluster_name, namespace


def query_clusters_for_hash_key_range_key_prefix(hash_key, range_key_prefix):
    ddb_client = boto3.client('dynamodb')
    eav = {
        ':hk' : {'S': hash_key},
        ':rk' : {'S': range_key_prefix}
    }

    try:
        response = ddb_client.query(TableName=KUBE_CLUSTERS_TABLE,
                    KeyConditionExpression='hash_key = :hk AND begins_with(range_key, :rk)',
                    ExpressionAttributeValues=eav)
    except Exception as ex:
        logger.warning("Kube cluster query failed: " + str(ex))
        return []

    cluster_list = []
    if 'Items' in response:
        for item in response['Items']:
            rk = item['range_key']['S']
            _, _, cluster_name, namespace = parse_access_range_key(rk)
            cluster_list.append((cluster_name, namespace))
    return cluster_list


def get_cluster_info_details(db_row):
    item = db_row
    owner, cluster_name, namespace = get_cluster_name_from_info_range_key(item['range_key']['S'])
    c_info = {
        'cluster_name': cluster_name,
        'namespace': namespace,
        'owner': owner,
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
        c_info['ecr_role'] = item['ecr_role']['S']
        c_info['ecr_role_ext'] = item['ecr_role_ext']['S']
        c_info['ecr_type'] = item['ecr_type']['S']
        c_info['ecr_region'] = item['ecr_region']['S']
    else:
        logger.warning("Invalid cluster definition")
        c_info = None
    return c_info


def query_cluster_info(cluster_name, namespace, owner):
    hash_key = get_cluster_info_hash_key()
    range_key = get_cluster_info_range_key(cluster_name, namespace, owner)
    ddb_client = boto3.client('dynamodb')
    key = {
        'hash_key' : {'S': hash_key},
        'range_key' : {'S': range_key}
    }

    response = ddb_client.get_item(TableName=KUBE_CLUSTERS_TABLE, Key=key)
    if 'Item' in response:
        item = response['Item']
        c_info = get_cluster_info_details(item)
    else:
        c_info = None
    return c_info


def query_clusters_info_by_owner(owner):
    hash_key = get_cluster_info_hash_key()
    range_key_prefix = get_cluster_info_range_key_prefix(owner)
    ddb_client = boto3.client('dynamodb')
    eav = {
        ':hk' : {'S': hash_key},
        ':rk' : {'S': range_key_prefix}
    }
    try:
        response = ddb_client.query(TableName=KUBE_CLUSTERS_TABLE,
                    KeyConditionExpression='hash_key = :hk AND begins_with(range_key, :rk)',
                    ExpressionAttributeValues=eav)
    except Exception as ex:
        logger.warning("Kube cluster query failed: " + str(ex))

    cluster_list = []
    if 'Items' in response:
        for item in response['Items']:
            c_info = get_cluster_info_details(item)
            if c_info:
                cluster_list.append(c_info)

    return cluster_list


def query_user_accessible_clusters(cognito_username, groups, is_admin):
    cluster_list = []
    hash_key = get_cluster_access_hash_key()
    range_key_prefix = get_cluster_access_range_key_prefix('user', cognito_username)
    more_clusters = query_clusters_for_hash_key_range_key_prefix(hash_key, range_key_prefix)
    cluster_list.extend(more_clusters)

    for g in groups or []:
        hash_key = get_cluster_access_hash_key()
        range_key_prefix = get_cluster_access_range_key_prefix('group', g)
        more_clusters = query_clusters_for_hash_key_range_key_prefix(hash_key, range_key_prefix)
        cluster_list.extend(more_clusters)

    ## Get cluster info
    cluster_info_list = []
    for cl_name, ns in cluster_list:
        owner = get_subscriber_name(cognito_username)
        cluster_info = query_cluster_info(cl_name, ns, owner)
        if cluster_info:
            if is_admin:
                cluster_info_list.append(cluster_info)
            else:
                ## For non-admin don't send all the information
                c_info = {}
                c_info['cluster_name'] = cluster_info['cluster_name']
                c_info['namespace'] = cluster_info['namespace']
                c_info['cluster_type'] = cluster_info['cluster_type']
                c_info['owner'] = cluster_info['owner']
                cluster_info_list.append(c_info)

    ## Get user's own clusters
    user_clusters = query_clusters_info_by_owner(cognito_username)
    cluster_info_list.extend(user_clusters)

    return cluster_info_list


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
    is_admin = is_user_admin(cognito_username)

    if is_admin:
        ##Fetch all admin controlled clusters
        subscriber = get_subscriber_name(cognito_username)
        cluster_list = query_clusters_info_by_owner(subscriber)
        if subscriber != cognito_username:
            user_cluster = query_clusters_info_by_owner(cognito_username)
            cluster_list.extend(user_cluster)
        ## User and group access
        user_access = query_cluster_access_records('user')
        group_access = query_cluster_access_records('group')
        access_grouped_by_cluster = {}
        for principal_type, principal, cluster_name, namespace in user_access + group_access:
            if (cluster_name, namespace) not in access_grouped_by_cluster:
                access_grouped_by_cluster[(cluster_name, namespace)] = []
            access_grouped_by_cluster[(cluster_name, namespace)]\
                .append({'principal_name': principal, 'principal_type': principal_type})

        for cl in cluster_list:
            cl_name = cl['cluster_name']
            ns = cl['namespace']
            if (cl_name, ns) in access_grouped_by_cluster:
                cl['cluser_access'] = access_grouped_by_cluster[(cl_name, ns)]
    else:
        ##Get clusters that this user has access to
        cluster_list = query_user_accessible_clusters(cognito_username, groups, is_admin)

    if cluster_list:
        return respond(None, {'kube_clusters': cluster_list})
    else:
        return respond(None, dict())


def add_cluster_access(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    is_admin = is_user_admin(cognito_username)

    if not is_admin:
        return respond('Only admin can change access', None)

    body = event['body']
    item = json.loads(body)

    cluster_name = item['cluster_name']
    namespace = item['namespace']

    cluster_info = query_cluster_info(cluster_name, namespace, get_subscriber_name(cognito_username))

    ## It may be a user cluster, admin cannot grant access to a cluster owned by another user
    ## Currently, grant/revoke access on user clusters is not supported
    if not cluster_info:
        print(f'No admin cluster found for name {cluster_name} and namespace {namespace}')
        return respond(f'No admin cluster found for name {cluster_name} and namespace {namespace}', None)

    if 'principal_type' in item:
        principal_type = item['principal_type']
    else:
        principal_type = 'user'

    if 'principal_name' in item:
        principal_name = item['principal_name']
    else:
        return respond("Principal name not specified", None)

    hash_key = get_cluster_access_hash_key()
    range_key = get_cluster_access_range_key(principal_type, principal_name, cluster_name, namespace)

    record = {
        'hash_key': {'S': hash_key},
        'range_key': {'S': range_key}
    }
    ddb_client = boto3.client('dynamodb')
    try:
        ddb_client.put_item(TableName=KUBE_CLUSTERS_TABLE, Item=record)
    except Exception as ex:
        logger.warning("Failed to add cluster access: " + str(ex))
        return respond("Failed to add cluster access", dict())

    return respond(None, dict())


def remove_cluster_access(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    is_admin = is_user_admin(cognito_username)

    if not is_admin:
        return respond('Only admin can change access', None)

    body = event['body']
    item = json.loads(body)

    cluster_name = item['cluster_name']
    namespace = item['namespace']

    ## It may be a user cluster, admin cannot revoke access to a cluster owned by another user
    ## Currently, grant/revoke access on user clusters is not supported
    cluster_info = query_cluster_info(cluster_name, namespace, get_subscriber_name(cognito_username))
    if not cluster_info:
        print(f'No admin cluster found for name {cluster_name} and namespace {namespace}')
        return respond(f'No admin cluster found for name {cluster_name} and namespace {namespace}', None)

    if 'principal_type' in item:
        principal_type = item['principal_type']
    else:
        principal_type = 'user'

    if 'principal_name' in item:
        principal_name = item['principal_name']
    else:
        return respond("Principal name not specified", None)

    hash_key = get_cluster_access_hash_key()
    range_key = get_cluster_access_range_key(principal_type, principal_name, cluster_name, namespace)

    key = {
        'hash_key': {'S': hash_key},
        'range_key': {'S': range_key}
    }
    ddb_client = boto3.client('dynamodb')
    try:
        ddb_client.delete_item(TableName=KUBE_CLUSTERS_TABLE, Key=key)
    except Exception as ex:
        logger.warning("Failed to add cluster access: " + str(ex))
        return respond("Failed to add cluster access", dict())

    return respond(None, dict())