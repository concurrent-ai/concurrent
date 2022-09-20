import logging
import ast
from typing import Tuple

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_resource_ids_given_keys_internal(client, table_name, version, hashkey, rangekey_prefix,
                                        limit = -1, last_evaluated_key = None):
    eav = dict()
    un = dict()
    un['S'] = hashkey
    eav[':un'] = un
    ei = dict()
    ei['S'] = rangekey_prefix
    eav[':ei'] = ei

    if limit < 0:
        #This will never be reached because result size is limited to 1MB
        one_query_limit = 1000000
    else:
        one_query_limit = limit

    resource_id_list = []
    while True:
        try:
            if (last_evaluated_key != None):
                logger.info('querying: ExclusiveStartKey=' + str(last_evaluated_key))
                query_result = client.query(TableName=table_name,\
                    KeyConditionExpression='hash_key = :un AND begins_with(range_key, :ei)',\
                    ExpressionAttributeValues=eav, ExclusiveStartKey=last_evaluated_key, Limit=one_query_limit)
            else:
                logger.info('querying: No ExclusiveStartKey')
                query_result = client.query(TableName=table_name,\
                    KeyConditionExpression='hash_key = :un AND begins_with(range_key, :ei)',\
                    ExpressionAttributeValues=eav, Limit=one_query_limit)
        except Exception as ex:
            logger.info(str(ex))
            raise ex

        if 'Items' in query_result:
            items = query_result['Items']
        else:
            items = []
        for ind in range(len(items)):
            item = items[ind]
            resource_id_string = item['range_key']['S'][len(rangekey_prefix):]
            if resource_id_string.isnumeric():
                resource_id = str(int(resource_id_string))
            else:
                resource_id = resource_id_string
            resource_id_list.append(resource_id)

        if 'LastEvaluatedKey' in query_result:
            last_evaluated_key = query_result['LastEvaluatedKey']
        else:
            last_evaluated_key = None

        if 0 < limit <= len(resource_id_list):
            return resource_id_list[0:limit], last_evaluated_key
        elif last_evaluated_key:
            continue
        else:
            logger.info("LastEvaluatedKey not present. Breaking and returning..")
            break

    return resource_id_list, last_evaluated_key


def ddb_batch_write_items(client, table_name, batch_to_execute):
    size_per_batch = 25
    index = 0
    while index < len(batch_to_execute):
        if index + size_per_batch < len(batch_to_execute):
            last_index = index + size_per_batch
        else:
            last_index = len(batch_to_execute)
        batch_requests = batch_to_execute[index:last_index]
        try_count = 3
        while try_count > 0:
            response = client.batch_write_item(RequestItems={table_name: batch_requests})
            if 'UnprocessedItems' in response and response['UnprocessedItems']:
                batch_requests = response['UnprocessedItems']
            else:
                break
            try_count -= 1
        index = index + size_per_batch

##Dynamodb limits number of transactions to 25
##More transactions are done in batches of 25 and are non-atomic.
def ddb_transaction_write_items(client, transaction_to_execute):
    txn_count = len(transaction_to_execute)
    logger.info("Number of transactions: "+ str(txn_count))
    logger.info(str(transaction_to_execute))
    size_per_batch = 25
    index = 0
    while index < txn_count:
        if index + size_per_batch < txn_count:
            last_index = index + size_per_batch
        else:
            last_index = txn_count
        batch_txns = transaction_to_execute[index:last_index]
        client.transact_write_items(TransactItems=batch_txns)
        index = index + size_per_batch


def get_resource_roles_internal(client, table_name, hash_key, range_key_prefix) -> dict:
    """
    for the specified 'resource' (specified in the 'hash_key'), returns the following: 
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
    """
    key_condition_expression = "hash_key = :hk and begins_with(range_key, :rkp)"

    eav = {
        ':hk': {'S': hash_key},
        ':rkp': {'S': range_key_prefix}
    }

    query_result = client.query(TableName=table_name, KeyConditionExpression=key_condition_expression,
                                ExpressionAttributeValues=eav)

    roles = {
        'user_roles': {},
        'group_roles': {}
    }
    if 'Items' in query_result:
        for item in query_result['Items']:
            rk = item['range_key']['S']
            type, id = rk[len(range_key_prefix):].split('/')
            if type == 'user':
                roles['user_roles'][id] = item['role']['S']
            elif type == 'group':
                roles['group_roles'][id] = item['role']['S']

    return roles


def get_tag_list(tag_str):
    tags_list = ast.literal_eval(tag_str)

    # Empty ddb_entry gets parsed as an empty dict,
    # ensure it is returned as an empty list
    if not tags_list:
        tags_list = []
    return tags_list