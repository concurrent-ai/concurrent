import json
import logging
import time
import uuid
import copy
import os
import re
import boto3
import ddb_mlflow_parallels_queries as ddb_pqrs
from mlflow_utils import fetch_mlflow_artifact_file
from utils import get_custom_token

logger = logging.getLogger()
logger.setLevel(logging.INFO)
DAG_INFO_TABLE = os.environ['DAG_TABLE']
DAG_EXECUTION_TABLE = os.environ['DAG_EXECUTION_TABLE']
#DAG_EXECUTION_TABLE = "concurrent-dag-execution"
DAG_RUNTIME_ARTIFACT = 'dag_runtime.json.bin'

def fetch_dag_details(cognito_username, dag_id):

    parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, dag_id)
    if parallel_info:
        dag_info = parallel_info
        dag_info['dagid'] = dag_id
        dag_info['name'] = parallel_info['parallel_name']
        dag_json = json.loads(parallel_info['parallel_json'])
        dag_info['nodes'] = dag_json['node']
        dag_info['edges'] = dag_json.get('edge')
    else:
        msg = 'Could not find dag '+str(dag_id) + ", for user "+cognito_username
        raise(msg)
    return dag_info

def create_dag_execution_record(cognito_username, dag_id, dag_execution_id, status, dag_json,
                                parent_run_id, auth_info):
    client = boto3.client('dynamodb')

    now = int(time.time())
    auth_info.pop('custom_token', None)
    auth_info.pop('custom_token_expiry', None)
    item = {
        'dag_id': {'S': dag_id},
        'dag_execution_id' : {'S' : dag_execution_id},
        'username': {'S' : cognito_username},
        'locked' : {'S': 'no'},
        'update_time' : {'N': str(now)},
        'authInfo' : {'S': json.dumps(auth_info)},
        'parent_run_id': {'S': parent_run_id},
        'start_time': {'N': str(now)}
    }

    try:
        client.put_item(TableName=DAG_EXECUTION_TABLE, Item=item)
    except Exception as ex:
        status_msg = 'caught while updating dag status' + str(ex)
        logger.info(status_msg)
        raise Exception(status_msg)
    return

def get_new_dag_exec_id(dagid):
    return dagid + "-" + str(uuid.uuid1())

def hash_key(nodeid):
    return abs(int(hash(nodeid))) % 100

def edge_key_sorter(record):
    src_hash = hash_key(record[0])
    tgt_hash = hash_key(record[1])
    return src_hash * 10000 + tgt_hash

def create_new_dag_json(old_dag_json, new_node_dict, new_edge_dict):
    new_dag_json = copy.deepcopy(old_dag_json)
    new_dag_json['edges'] = []
    new_dag_json['nodes'] = []
    for edge in sorted(new_edge_dict, key=edge_key_sorter):
        new_dag_json['edges'].append({'source': edge[0], 'target': edge[1]})
    for key, value in new_node_dict.items():
        new_dag_json['nodes'].append(value)

    #print('New Dag Json#')
    #print(json.dumps(new_dag_json, indent=4, sort_keys=True))
    ##print(new_dag_json)
    return new_dag_json


# def check_and_update_auth_info(cognito_username, groups, dag_id, dag_execution_id, record):
#     auth_info = record['auth_info']
#     if 'custom_token_expiry' in auth_info and int(auth_info['custom_token_expiry']) >= time.time() + 60*60:
#         return record
#     else:
#         ##Update custom token
#         ##The user must be authorized for this dag_id.
#         logger.info('custom token almost expired, fetch a new one')
#         token_info = get_custom_token(cognito_username, groups)
#         queue_message_uuid = token_info['queue_message_uuid']
#         token = token_info['token']
#         expiry = token_info['expiry']
#         custom_token = "Custom {0}:{1}".format(queue_message_uuid, token)
#         auth_info['custom_token'] = custom_token
#         auth_info['custom_token_expiry'] = expiry
#         record['auth_info'] = auth_info
#
#         client = boto3.client('dynamodb')
#         key = dict()
#         hk = dict()
#         hk['S'] = dag_id
#         key['dag_id'] = hk
#         rk = dict()
#         rk['S'] = dag_execution_id
#         key['dag_execution_id'] = rk
#
#         uxp = 'SET auth_info = :ai'
#         eav = {
#             ":ai": {"S": json.dumps(auth_info)},
#         }
#
#         try:
#             client.update_item(TableName=DAG_EXECUTION_TABLE, Key=key, UpdateExpression=uxp,
#                                ExpressionAttributeValues=eav)
#             return record
#         except Exception as ex:
#             status_msg = 'caught while updating auth_info' + str(ex)
#             raise Exception(status_msg)



def get_dag_execution_record(cognito_username, groups, dag_id, dag_execution_id):
    client = boto3.client('dynamodb')

    key = dict()
    hk = dict()
    hk['S'] = dag_id
    key['dag_id'] = hk
    rk = dict()
    rk['S'] = dag_execution_id
    key['dag_execution_id'] = rk

    try:
        dag_execution_result = client.get_item(TableName=DAG_EXECUTION_TABLE, Key=key)
    except Exception as ex:
        status_msg = 'caught while fetching dag status' + str(ex)
        logger.info(status_msg)
        raise(status_msg)

    if 'Item' in dag_execution_result:
        item = dag_execution_result['Item']
        auth_info = json.loads(item['authInfo']['S'])
        record = {
            'dag_id': dag_id,
            'dag_execution_id': dag_execution_id,
            'auth_info': auth_info,
            'update_time': item['update_time']['N'],
            'parent_run_id': item['parent_run_id']['S']
        }
        if 'start_time' in item:
            record['start_time'] = item['start_time']['N']
        ##record = check_and_update_auth_info(cognito_username, groups, dag_id, dag_execution_id, record)
        return record
    else:
        msg = 'Could not find dag execution status for '+str(dag_id) + ", for user "+cognito_username
        raise(msg)

def get_dag_execution_list(cognito_username, dagid):
    client = boto3.client('dynamodb')

    key_condition_expression = "dag_id = :di"
    expression_attr_vals = {
        ":di" : {"S" : dagid}
    }

    response = client.query(TableName=DAG_EXECUTION_TABLE,
                            ProjectionExpression="dag_execution_id, authInfo, update_time, start_time, parent_run_id",
                            KeyConditionExpression=key_condition_expression,
                            ExpressionAttributeValues=expression_attr_vals
                            )
    if response and response.get('Items'):
        result = []
        for item in response.get('Items'):
            result.append(get_projections(item))
        return result
    else:
        return []

def get_projections(item):
    result =  {
        'dag_execution_id': item['dag_execution_id']['S'],
        'update_time': str(item['update_time']['N'])
    }
    if 'start_time' in item:
        result['start_time'] = str(item['start_time']['N'])
    if 'parent_run_id' in item:
        result['parent_run_id'] = str(item['parent_run_id']['S'])
    if 'authInfo' in item:
        result['auth_info'] = json.loads(item['authInfo']['S'])
    return result

def get_named_input_spec_map(inputs):
    named_map = dict()
    for item in inputs:
        name = item['name']
        if name not in named_map:
            named_map[name] = list()
        named_map[name].append(item)
    return named_map

def get_spec_list_from_named_input_map(named_map):
    input_list = list()
    for key, vals in named_map.items():
        input_list = input_list + vals
    return input_list


def fetch_dag_execution_info(cognito_username, groups, dag_id, dag_execution_id):
    record = get_dag_execution_record(cognito_username, groups, dag_id, dag_execution_id)
    dag_runtime_info = fetch_dag_runtime_artifact(cognito_username, groups,
                                                  record['auth_info'], record['parent_run_id'])
    record['dag_json'] = dag_runtime_info['dag_json']
    record['run_status'] = dag_runtime_info['run_status']
    return record


def fetch_dag_runtime_artifact(cognito_username, groups, authinfo, parent_run_id):
    dag_runtime_path = os.path.join('.concurrent', DAG_RUNTIME_ARTIFACT)
    artifact_content = fetch_mlflow_artifact_file(cognito_username, groups, authinfo, parent_run_id, dag_runtime_path)
    dag_runtime_info = json.loads(artifact_content.decode('utf-8'))
    return dag_runtime_info

def fetch_dag_json(cognito_username, dag_id):
    parallel_info = ddb_pqrs.get_parallel_by_id(cognito_username, dag_id)
    if parallel_info:
        return json.loads(parallel_info['parallel_json'])
    else:
        msg = 'Could not find dag '+str(dag_id) + ", for user "+cognito_username
        raise(msg)
