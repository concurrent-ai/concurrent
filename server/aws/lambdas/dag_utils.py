import json
import logging
import time
import uuid
import copy
import os
import re
import boto3
import ddb_mlflow_parallels_queries as ddb_pqrs

logger = logging.getLogger()
logger.setLevel(logging.INFO)
DAG_INFO_TABLE = os.environ['DAG_TABLE']
DAG_EXECUTION_TABLE = os.environ['DAG_EXECUTION_TABLE']

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

def create_dag_execution_record(cognito_username, dag_id, dag_execution_id, status, dag_json, auth_info):
    client = boto3.client('dynamodb')

    now = int(time.time())
    item = {
        'dag_execution_id' : {'S' : dag_execution_id},
        'username': {'S' : cognito_username},
        'dagid': {'S': dag_id},
        'run_status': {'S': json.dumps(status)},
        'locked' : {'S': 'no'},
        'update_time' : {'N': str(now)},
        'dagJson' : {'S': json.dumps(dag_json)},
        'authInfo' : {'S': json.dumps(auth_info)},
        'start_time': {'N': str(now)}
    }

    try:
        client.put_item(TableName=DAG_EXECUTION_TABLE, Item=item)
    except Exception as ex:
        status_msg = 'caught while updating dag status' + str(ex)
        logger.info(status_msg)
        raise(status_msg)
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


def get_dag_execution_record(cognito_username, dag_id, dag_execution_id):
    client = boto3.client('dynamodb')

    key = dict()
    hk = dict()
    hk['S'] = cognito_username
    key['username'] = hk
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
        if dag_id != item['dagid']['S']:
            msg = "Invalid dag execution id " + str(dag_execution_id) + "for dag " + str(dag_id)
            raise(msg)
        dag_run_status =  json.loads(item['run_status']['S'])
        print(dag_run_status)
        dag_json = json.loads(item['dagJson']['S'])
        auth_info = json.loads(item['authInfo']['S'])
        record = {
            'dag_id': dag_id,
            'dag_execution_id': dag_execution_id,
            'dag_json': dag_json,
            'auth_info': auth_info,
            'run_status': dag_run_status,
            'update_time': item['update_time']['N']
        }
        if 'start_time' in item:
            record['start_time'] = item['start_time']['N']
        return record
    else:
        msg = 'Could not find dag execution status for '+str(dag_id) + ", for user "+cognito_username
        raise(msg)

def get_dag_execution_list(cognito_username, dagid):
    client = boto3.client('dynamodb')

    key_condition_expression = "username = :un AND begins_with(dag_execution_id, :dx)"
    expression_attr_vals = {
        ":un" : {"S" : cognito_username},
        ":dx" : {"S" : dagid}
    }

    response = client.query(TableName=DAG_EXECUTION_TABLE,
                            ProjectionExpression="dag_execution_id, update_time, start_time",
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
