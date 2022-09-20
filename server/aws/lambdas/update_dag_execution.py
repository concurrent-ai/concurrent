import json
import os
import logging
import time
import copy

import lock_utils, execute_dag, dag_utils
from utils import get_cognito_user

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DAG_EXECUTION_TABLE = os.environ['DAG_EXECUTION_TABLE']


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


def update_dag_execution(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    # logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)

    item = json.loads(event['body'])
    logger.info('payload item=' + str(item))
    run_id = item['run_id']
    dagid = item['dagid']
    dag_execution_id = item['dag_execution_id']

    if 'partitions' in item:
        partition_spec = item['partitions']
    else:
        raise Exception("Nothing to do")

    lock_key, lock_lease_time = execute_dag.acquire_idle_row_lock(cognito_username, dag_execution_id)

    try:
        dag_json, dag_execution_status, auth_info \
            = execute_dag.fetch_dag_execution_info(cognito_username, dagid, dag_execution_id)
        update_dag_execution_info(cognito_username, dag_execution_id, dag_execution_status,
                                  dag_json, run_id, partition_spec)
    except Exception as ex:
        status_msg = 'caught while fetching and updating dag execution info: ' + str(ex)
        logger.error(status_msg)
        logger.error(ex)
        raise Exception(status_msg)
    finally:
        execute_dag.release_row_lock(lock_key)
    return respond(None, dict())

def update_dag_execution_info(cognito_username, dag_execution_id, dag_execution_status,
                              dag_json, run_id, partition_list, test_call=False):
    incoming_edge_graph, outgoing_edge_graph, node_dict, edge_dict = execute_dag.get_graph_struct(dag_json)
    nodes_to_split = set()  ##Set of nodes to be partitioned
    partitioner_seed_node = None
    for node, node_status in dag_execution_status['nodes'].items():
        if run_id == node_status.get('run_id'):
            partitioner_seed_node = node
        else:
            continue

    if not partitioner_seed_node:
        print('Fatal: This should not happen')
        raise Exception('Graph structure is corrupted')

    print('Partitioner Seed Node = '+partitioner_seed_node)
    ## partitioner_seed node itself doesn't get partitioned. It is already executed.
    ## It is either a no-op node, or
    ## some of the consumers of it's output are going to be partitioned

    ## First populate nodes_to_split with direct connections from partitioner_seed_node
    direct_nodes_to_split = set()
    downstream_nodes = outgoing_edge_graph[partitioner_seed_node]
    for nodeid in downstream_nodes:
        for input in node_dict[nodeid]['input']:
            if  input['type'] == 'existing_xform' \
                and input['source'] == partitioner_seed_node:
                direct_nodes_to_split.add(nodeid)

    print("direct_nodes_to_split ##")
    print(direct_nodes_to_split)

    ## Now find all nodes to split using depth first search
    nodes_to_split.update(direct_nodes_to_split)

    ## Find edges to split
    incoming_edges_to_split = set()  ## Edges incoming into the nodes_to_split set.
    outgoing_edges_to_split = set()  ## Edges outgoing from the nodes_to_split set.
    internal_edges_to_split = set()  ## Edges internal to the nodes_to_split set
    for edge in edge_dict.keys():
        if edge[0] in nodes_to_split and edge[1] in nodes_to_split:
            internal_edges_to_split.add(edge)
        elif edge[0] in nodes_to_split and edge[1] not in nodes_to_split:
            outgoing_edges_to_split.add(edge)
        elif edge[0] not in nodes_to_split and edge[1] in nodes_to_split:
            incoming_edges_to_split.add(edge)

    ##Split the nodes
    splitted_nodes = {}
    for nodeid in nodes_to_split:
        index = 0
        split_list = []
        for partition in partition_list:
            new_node_id = get_new_node_id(nodeid, index)
            split_list.append(new_node_id)
            index += 1
        splitted_nodes[nodeid] = split_list

    print('Splitted Nodes ##')
    print(splitted_nodes)

    ##Split the edges
    splitted_edges = set()
    for edge in internal_edges_to_split:
        new_edges = split_internal_edge(splitted_nodes, edge)
        splitted_edges.update(new_edges)
    for edge in incoming_edges_to_split:
        new_edges = split_incoming_edge(splitted_nodes, edge)
        splitted_edges.update(new_edges)
    for edge in outgoing_edges_to_split:
        new_edges = split_outgoing_edge(splitted_nodes, edge, node_dict)
        splitted_edges.update(new_edges)

    print('Splitted edges ##')
    print(splitted_edges)

    ##Update the original graph
    new_dag_exec_status = copy.deepcopy(dag_execution_status)

    for nodeid in direct_nodes_to_split:
        old_input_spec = node_dict[nodeid]['input']
        new_node_info = copy.deepcopy(node_dict[nodeid])
        new_node_info['input'] = None
        new_input_spec = []
        parallelization = None
        for spec in old_input_spec:
            if spec['type'] == 'existing_xform' \
                    and spec['source'] == partitioner_seed_node:
                ##This input is replaced with the partition spec
                continue
            else:
                new_input_spec.append(spec)
        index = 0
        for partition in partition_list:
            new_node_info = copy.deepcopy(node_dict[nodeid])
            newnodeid = splitted_nodes[nodeid][index]
            new_node_info['id'] = newnodeid
            additional_spec = {}
            if parallelization:
                new_node_info['parallelization'] = parallelization
            additional_spec['type'] = partition['type']
            if 'run_id' in partition:
                additional_spec['input_run_id'] = partition['run_id']
            additional_spec['prefix'] = partition['prefix']
            ##Unsplitted prefix is the prefix before partitioning
            if 'unsplitted_prefix' in partition:
                additional_spec['unsplitted_prefix'] = partition['unsplitted_prefix']
            if 'time_spec' in partition:
                additional_spec['time_spec'] = partition['time_spec']
            if 'bucketname' in partition:
                additional_spec['bucketname'] = partition['bucketname']
            if 'name' in partition:
                additional_spec['name'] = partition['name']
            elif 'name' in old_input_spec:
                additional_spec['name'] = old_input_spec['name']
            new_node_info['input'] = copy.deepcopy(new_input_spec)
            new_node_info['input'].append(additional_spec)
            new_node_info['original_node'] = nodeid
            node_dict[newnodeid] = new_node_info
            index += 1
        node_dict.pop(nodeid)
        new_dag_exec_status['nodes'].pop(nodeid, None)


    for nodeid in splitted_nodes.keys():
        for newnodeid in splitted_nodes[nodeid]:
            new_dag_exec_status['nodes'][newnodeid] = {'status': 'PENDING'}

    ##Update the edges in the graph
    for edge in incoming_edges_to_split:
        edge_dict.pop(edge)
    for edge in outgoing_edges_to_split:
        edge_dict.pop(edge)
    for edge in internal_edges_to_split:
        edge_dict.pop(edge)

    for edge in splitted_edges:
        edge_dict[edge] = {'source': edge[0], 'target': edge[1]}

    ##Create new dag_json
    new_dag_json = dag_utils.create_new_dag_json(dag_json, node_dict, edge_dict)

    ##Now check for edge partitioned nodes
    ##Call multiple times as new splitted nodes can cause further splits
    modified = True
    while modified:
        new_dag_json, new_dag_exec_status, modified = update_edge_partitioned_nodes(new_dag_json, new_dag_exec_status)

    if not test_call:
        update_ddb_dag_exec_info(cognito_username, new_dag_json, dag_execution_id, new_dag_exec_status)
    return new_dag_json


def update_edge_partitioned_nodes(dag_json, dag_exec_status):
    incoming_edge_graph, outgoing_edge_graph, node_dict, edge_dict = execute_dag.get_graph_struct(dag_json)

    modified = False
    for node in list(node_dict.keys()):
        node_info = node_dict[node]
        inputs = node_info.get('input')
        if inputs:
            named_inputs = dag_utils.get_named_input_spec_map(inputs)
            for name, input_list in named_inputs.items():
                if len(input_list) > 1:
                    ##Multiple inputs with same name, if they are edge partitioned we can split them.
                    ##Inputs with same name must be result of an splitting of an edge.
                    ##If it is 'edge' partitioned, we can split this node, checking only one input is enough.
                    if 'partition_params' in input_list[0]:
                        if input_list[0]['partition_params'].get('partitioner') == 'edge':
                            node_dict, edge_dict, dag_exec_status = \
                                perform_edge_partitioned_split(node, name, node_dict,
                                                               edge_dict, named_inputs, dag_exec_status)
                            modified = True
                        elif input_list[0]['partition_params'].get('partitioner') == 'sliding':
                            node_dict, edge_dict, dag_exec_status = \
                                perform_sliding_partitioned_split(node, name, node_dict,
                                                                  edge_dict, named_inputs, dag_exec_status)
                            modified = True

    if modified:
        new_dag_json = dag_utils.create_new_dag_json(dag_json, node_dict, edge_dict)
    else:
        new_dag_json = dag_json
    return new_dag_json, dag_exec_status, modified

def find_outgoing_edges_to_split(node_to_split, edge_dict):
    outgoing_edges_to_split = set()  ## Edges outgoing from the nodes_to_split set.
    for edge in edge_dict.keys():
        if edge[0] == node_to_split:
            outgoing_edges_to_split.add(edge)
    return outgoing_edges_to_split

def perform_edge_partitioned_split(node, input_name, node_dict, edge_dict, named_inputs, dag_exec_status):
    splitting_node_info = node_dict.pop(node)
    dag_exec_status['nodes'].pop(node, None)
    new_node_list = set()
    index = 0
    for input in named_inputs[input_name]:
        edge_to_remove = (input['source'], node)
        new_node_info = copy.deepcopy(splitting_node_info)
        new_node_id = get_new_node_id(node, index)
        new_node_info['id'] = new_node_id
        new_node_list.add(new_node_id)
        index += 1
        edge_dict.pop(edge_to_remove)
        edge_dict[(input['source'], new_node_id)] = {'source': input['source'], 'target': new_node_id}
        new_named_input = copy.deepcopy(named_inputs)
        input.pop('partition_params')
        new_named_input.pop(input_name)
        new_named_input[input_name] = [input]
        new_node_info['input'] = dag_utils.get_spec_list_from_named_input_map(new_named_input)
        node_dict[new_node_id] = new_node_info
        dag_exec_status['nodes'][new_node_id] = {'status': 'PENDING'}

    splitted_nodes = {node: new_node_list}
    outgoing_edges_to_split = find_outgoing_edges_to_split(node, edge_dict)
    for edge in outgoing_edges_to_split:
        new_edges = split_outgoing_edge(splitted_nodes, edge, node_dict)
        edge_dict.pop(edge)
        for new_e in new_edges:
            edge_dict[new_e] = {'source': new_e[0], 'target': new_e[1]}

    ##Check other input edges of the splitting node
    for input in splitting_node_info['input']:
        if input['name'] != input_name and input['type'] == 'existing_xform':
            edge_to_split = (input['source'], node)
            new_edges = split_incoming_edge(splitted_nodes, edge_to_split)
            edge_dict.pop(edge_to_split)
            for new_e in new_edges:
                edge_dict[new_e] = {'source': new_e, 'target': new_e[1]}

    return node_dict, edge_dict, dag_exec_status

def perform_sliding_partitioned_split(node, input_name,
                                      node_dict, edge_dict, named_inputs, dag_exec_status):
    splitting_node_info = node_dict.pop(node)
    dag_exec_status['nodes'].pop(node, None)
    new_node_list = set()
    input_list = named_inputs[input_name]
    sliding_window = int(input_list[0]['partition_params'].get('window'))
    num_new_nodes = len(input_list) - sliding_window + 1
    for index in range(num_new_nodes):
        new_node_info = copy.deepcopy(splitting_node_info)
        new_node_id = get_new_node_id(node, index)
        new_node_info['id'] = new_node_id
        new_node_list.add(new_node_id)
        new_named_input = copy.deepcopy(named_inputs)
        new_named_input.pop(input_name)
        new_input_list = []
        for input in input_list[index : index+sliding_window]:
            edge_dict[(input['source'], new_node_id)] = {'source': input['source'], 'target': new_node_id}
            input_copy = copy.deepcopy(input)
            input_copy.pop('partition_params')
            new_input_list.append(input_copy)
        new_named_input[input_name] = new_input_list
        new_node_info['input'] = dag_utils.get_spec_list_from_named_input_map(new_named_input)
        node_dict[new_node_id] = new_node_info
        dag_exec_status['nodes'][new_node_id] = {'status': 'PENDING'}

    for input in input_list:
        edge_to_remove = (input['source'], node)
        edge_dict.pop(edge_to_remove)

    splitted_nodes = {node: new_node_list}
    outgoing_edges_to_split = find_outgoing_edges_to_split(node, edge_dict)
    for edge in outgoing_edges_to_split:
        new_edges = split_outgoing_edge(splitted_nodes, edge, node_dict)
        edge_dict.pop(edge)
        for new_e in new_edges:
            edge_dict[new_e] = {'source': new_e[0], 'target': new_e[1]}

    ##Check other input edges of the splitting node
    for input in splitting_node_info['input']:
        if input['name'] != input_name and input['type'] == 'existing_xform':
            edge_to_split = (input['source'], node)
            new_edges = split_incoming_edge(splitted_nodes, edge_to_split)
            edge_dict.pop(edge_to_split)
            for new_e in new_edges:
                edge_dict[new_e] = {'source': new_e, 'target': new_e[1]}

    return node_dict, edge_dict, dag_exec_status

        ###TODO: edge_to_remove =


def get_new_node_id(old_nodeid, index):
    return old_nodeid + "-" + str(index + 1)

def split_internal_edge(splitted_nodes, edge):
    splitted_edges = set()
    index = 0
    first_node = edge[0]
    second_node = edge[1]
    for new_first_node in splitted_nodes[first_node]:
        new_second_node = splitted_nodes[second_node][index]
        index += 1
        new_edge = (new_first_node, new_second_node)
        splitted_edges.add(new_edge)
    return splitted_edges

def split_incoming_edge(splitted_nodes, edge):
    new_edges = set()
    first_node = edge[0]
    second_node = edge[1]
    ## first node is not split
    for new_second_node in splitted_nodes[second_node]:
        new_edge = (first_node, new_second_node)
        new_edges.add(new_edge)
    return new_edges

def split_outgoing_edge(splitted_nodes, edge, node_dict):
    new_edges = set()
    first_node = edge[0]
    second_node = edge[1]
    second_node_info = node_dict[second_node]
    second_node_inputs = second_node_info['input']
    for input in second_node_inputs:
        if input['type'] == 'existing_xform' and first_node == input['source']:
            existing_xform_input = input
            break
    second_node_inputs.remove(existing_xform_input)
    ## first node is not split
    for new_first_node in splitted_nodes[first_node]:
        new_edge = (new_first_node, second_node)
        new_edges.add(new_edge)
        new_existing_xform_input = copy.deepcopy(existing_xform_input)
        new_existing_xform_input['source'] = new_first_node
        second_node_inputs.append(new_existing_xform_input)
    return new_edges


def update_ddb_dag_exec_info(cognito_username, dag_json, dag_execution_id, dag_exec_status):
    client = boto3.client('dynamodb')

    dag_exec_key = execute_dag.create_dag_execution_key(cognito_username, dag_execution_id)

    now = int(time.time())
    uxp = 'SET dagJson = :ps, run_status = :rs, update_time = :ut'
    eav = {
        ":ps": {"S": json.dumps(dag_json)},
        ":rs": {"S": json.dumps(dag_exec_status)},
        ":ut": {"N": str(now)}
    }

    try:
        client.update_item(TableName=DAG_EXECUTION_TABLE, Key=dag_exec_key, UpdateExpression=uxp,
                           ExpressionAttributeValues=eav)
        return True
    except Exception as ex:
        status_msg = 'caught while updating dag_json' + str(ex)
        raise Exception(status_msg)
