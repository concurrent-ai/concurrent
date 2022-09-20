import logging
import time
import ast
from botocore.exceptions import ClientError
from utils import get_ddb_boto3_client_parallels
import ddb_helper_utils as ddbutils

logger = logging.getLogger()
logger.setLevel(logging.INFO)

############################################################
##  hash_key and range_key functions
############################################################

def get_range_key_urole_parallel(version, parallel_id):
    return version + '/parallels/' + parallel_id


def get_range_key_prefix_urole_parallel(version):
    return version + '/parallels/'


get_range_key_grole_parallel = get_range_key_urole_parallel


get_range_key_prefix_grole_parallel = get_range_key_prefix_urole_parallel


def get_hash_key_urole(userid):
    return 'urole/' + userid


def get_hash_key_grole(groupid):
    return 'grole/' + groupid


def get_hash_key_parallelinfo():
    return 'parallelinfo/'


def get_range_key_parallelinfo(version, parallel_id):
    return version + '/' + parallel_id


def get_hash_key_parallelrole(parallel_id):
    """ returns parallelrole/<parallel_id> """
    return 'parallelrole/' + parallel_id


def get_range_key_parallelrole_user(version, user = None):
    if user:
        return version + '/user/' + user
    else:
        return version + '/user/'


def get_range_key_parallelrole_group(version, group=None):
    if group:
        return version + '/group/' + group
    else:
        return version + '/group/'


def get_range_key_prefix_parallelrole(version):
    """ returns <version>/ """
    return version + '/'


def get_hash_key_parallelname():
    return 'parallelname/'


def get_range_key_parallelname(version, parallel_name):
    return version + '/' + parallel_name

############################################################################
##  Parallel Queries
############################################################################

def get_parallels_for_user(username, userid):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    hashkey = get_hash_key_urole(userid)
    rangekey_prefix = get_range_key_prefix_urole_parallel(version)
    return ddbutils.get_resource_ids_given_keys_internal(client, table_name, version, hashkey,
                                               rangekey_prefix)


def get_parallels_for_group(username, groupid):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    hashkey = get_hash_key_grole(groupid)
    rangekey_prefix = get_range_key_prefix_grole_parallel(version)
    return ddbutils.get_resource_ids_given_keys_internal(client, table_name, version, hashkey,
                                               rangekey_prefix)


def search_parallel_ids_from_name(username, parallel_name_prefix):
    table_name, version, client = get_ddb_boto3_client_parallels(username)

    key_condition_expression = "hash_key =:hk and begins_with(range_key, :rk)"
    eav = {
        ':hk': {'S': get_hash_key_parallelname()},
        ':rk': {'S': get_range_key_parallelname(version, parallel_name_prefix)}
    }
    query_result = client.query(TableName=table_name, KeyConditionExpression=key_condition_expression,
                                ExpressionAttributeValues=eav)

    if 'Items' in query_result:
        results = [item['parallel_id']['S'] for item in query_result['Items']]
        return results
    else:
        return []


def get_parallel_by_id(username, parallel_id):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    key = dict()
    hk = dict()
    hk['S'] = get_hash_key_parallelinfo()
    key['hash_key'] = hk
    rk = dict()
    rk['S'] = get_range_key_parallelinfo(version, parallel_id)
    key['range_key'] = rk

    gi_result = client.get_item(TableName=table_name, Key=key)
    if 'Item' in gi_result:
        parallel_info = _extract_parallel_info(gi_result['Item'], parallel_id)
        return parallel_info
    else:
        return None


def get_parallel_by_name(username, parallel_name):
    result = search_parallel_ids_from_name(username, parallel_name)
    for parallel_id in result:
        p = get_parallel_by_id(username, parallel_id)
        if parallel_name == p['parallel_name']:
            return p
    return None


def get_parallel_info_multiple(cognito_username, parallel_id_list):
    table_name, version, client = get_ddb_boto3_client_parallels(cognito_username)
    hash_key = get_hash_key_parallelinfo()

    eav = {
        ':hk': {'S': hash_key}
    }

    item_list = []
    last_evaluated_key = None
    while True:
        try:
            if last_evaluated_key:
                gi_result = client.query(TableName=table_name,
                                         KeyConditionExpression='hash_key = :hk',
                                         ExpressionAttributeValues=eav,
                                         ExclusiveStartKey=last_evaluated_key)
            else:
                gi_result = client.query(TableName=table_name,
                                         KeyConditionExpression='hash_key = :hk',
                                         ExpressionAttributeValues=eav)
            if 'Items' in gi_result:
                item_list = item_list + gi_result['Items']

            if ('LastEvaluatedKey' in gi_result):
                last_evaluated_key = gi_result['LastEvaluatedKey']
            else:
                logger.info("get_parallel_info_multiple: LastEvaluatedKey not present. Breaking and returning..")
                break
        except Exception as ex:
            status_msg = 'caught while get_parallel_info_multiple' + str(ex)
            logger.info(status_msg)
            raise ex

    if item_list:
        return _process_parallel_info_db_data(item_list, set(parallel_id_list))
    else:
        return dict()


def get_parallel_tags(username, parallel_id):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    key = dict()
    hk = dict()
    hk['S'] = get_hash_key_parallelinfo()
    key['hash_key'] = hk
    rk = dict()
    rk['S'] = get_range_key_parallelinfo(version, parallel_id)
    key['range_key'] = rk

    gi_result = client.get_item(TableName=table_name, Key=key, ProjectionExpression="tags")
    if 'Item' in gi_result and 'tags' in gi_result['Item']:
        return gi_result['Item']['tags']['S']
    else:
        return None


def get_parallel_roles(cognito_username, parallel_id) -> dict:
    """ for the specified parallel_id, return the following:
    {
     "user_roles": {
         <user_name>:<role>,
         <user_name>:<role>,
     },
     "group_roles": {
         <group_name>:<role>,
         <group_name>:<role>,
     }
    }

    Args:
        cognito_username (str): current authenticated user
        parallel_id (str): parallel_id

    Returns:
        dict: see above
    """
    table_name, version, client = get_ddb_boto3_client_parallels(cognito_username)
    hash_key = get_hash_key_parallelrole(parallel_id)
    range_key_prefix = get_range_key_prefix_parallelrole(version)
    return ddbutils.get_resource_roles_internal(client, table_name, hash_key, range_key_prefix)


def get_authorization_status(cognito_username):
    table_name, version, client = get_ddb_boto3_client_parallels(cognito_username)
    response = client.get_item(TableName=table_name,
                Key={'hash_key': {'S': '-'},
                      'range_key': {'S': version + '/authorization/authorization_enabled'}})
    if 'Item' in response:
        item = response['Item']
        return item['status']['S']
    else:
        ##Auth disabled by default
        return 'False'


def set_authorization_status(cognito_username, value_to_set):
    table_name, version, client = get_ddb_boto3_client_parallels(cognito_username)
    if (value_to_set):
        val = 'true'
    else:
        val = 'false'
    try:
        response = client.update_item(TableName=table_name,
            Key={'hash_key': {'S': '-'},
                'range_key': {'S': version + '/authorization/authorization_enabled'}},
            UpdateExpression='SET #s = :sv',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':sv': {'S': val}},
            ReturnValues='UPDATED_NEW')
        return True
    except Exception as ex:
        logger.info("set_is_authorization_enabled: Error " + str(ex))
        return False


def _extract_parallel_id_from_range_key(rk):
    return rk.split("/")[1]


def _extract_parallel_info(db_item, parallel_id=None):
    parallel_info = dict()
    if not parallel_id:
        parallel_id = _extract_parallel_id_from_range_key(db_item['range_key']['S'])
    parallel_info['parallel_id'] = parallel_id
    parallel_info['dagid'] = parallel_id
    parallel_info['parallel_name'] = db_item['parallel_name']['S']
    parallel_info['dagName'] = db_item['parallel_name']['S']
    parallel_info['dagJson'] = db_item['parallel_json']['S']
    parallel_info['parallel_json'] = db_item['parallel_json']['S']
    if 'description' in db_item:
        parallel_info['description'] = db_item['description']['S']
    if 'experiment_id' in db_item:
        parallel_info['experiment_id'] = db_item['experiment_id']['S']
    parallel_info['creator'] = db_item['creator']['S']
    if ('tags' in db_item):
        tags_array = ast.literal_eval(db_item['tags']['S'])
        parallel_info['tags'] = tags_array
    return parallel_info


def _process_parallel_info_db_data(item_list, parallel_id_set):
    parallel_info_list = []
    for db_item in item_list:
        parallel_id = _extract_parallel_id_from_range_key(db_item['range_key']['S'])
        if parallel_id in parallel_id_set:
            parallel_info = _extract_parallel_info(db_item, parallel_id)
            parallel_info_list.append(parallel_info)
    return parallel_info_list



