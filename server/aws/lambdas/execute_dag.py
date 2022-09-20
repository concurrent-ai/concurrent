import logging
import json
import os
import uuid
import time
import copy
from datetime import datetime, timezone
import boto3
from urllib.parse import urlparse, unquote
import concurrent.futures

from utils import get_cognito_user, get_service_conf, create_request_context, get_custom_token
import period_run, lock_utils, dag_utils, run_project
from mlflow_utils import call_create_run, fetch_run_id_info, update_run, create_experiment, log_mlflow_artifact
import ddb_mlflow_parallels_txns as ddb_txns

logger = logging.getLogger()
logger.setLevel(logging.INFO)
DAG_EXECUTION_TABLE = dag_utils.DAG_EXECUTION_TABLE

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

def extract_run_params(body):
    run_params = {}
    bs = body.split('&')
    for obs in bs:
        obss = obs.split('=')
        if len(obss) == 2:
            if obss[0] == 'dagid':
                run_params['dagid'] = obss[1]
            elif obss[0] == 'dagParamsJson':
                run_params['dagParamsJson'] = obss[1]
            elif obss[0] == 'MLFLOW_TRACKING_URI':
                run_params['MLFLOW_TRACKING_URI'] = obss[1]
            elif obss[0] == 'MLFLOW_TRACKING_TOKEN':
                run_params['MLFLOW_TRACKING_TOKEN'] = obss[1]
            elif obss[0] == 'MLFLOW_PARALLELS_URI':
                run_params['MLFLOW_PARALLELS_URI'] = obss[1]
            elif obss[0] == 'MLFLOW_EXPERIMENT_ID':
                run_params['experiment_id'] = obss[1]
    if not run_params:
        run_params = json.loads(body)
    return run_params

def execute_dag(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    httpOperation = event.get('httpMethod')
    if httpOperation:
        print('Http call')
        if (httpOperation != 'POST'):
            return respond(ValueError('Unsupported method ' + str(httpOperation)))
        cognito_username, groups = get_cognito_user(event)
        b1 = event['body']
        body = unquote(b1)
        print('incoming body=' +str(body))
        run_params = extract_run_params(body)
        print('run_params=' + str(run_params))
    else:
        print('Lambda invocation')
        cognito_username = event['username']
        groups = [] # XXX need to get groups from caller
        run_params = event

    success, status, service_conf = get_service_conf()
    if (success == False):
        err = 'execute_dag: Error {0} lookup service conf'.format(status)
        logger.error(err)
        return respond(ValueError(err))

    dag_id = run_params['dagid']
    dag_execution_id = None
    if 'dagExecutionId' in run_params:
        dag_execution_id = run_params['dagExecutionId']
    elif 'dag_execution_id' in run_params:
        dag_execution_id = run_params.get('dag_execution_id')
    periodic_run_name = run_params.get('periodic_run_name')

    frequency = run_params.get('frequency')
    dagParamsJsonRuntime = None
    if 'dagParamsJson' in run_params:
        dagParamsJsonRuntime = json.loads(run_params['dagParamsJson'])

    print(cognito_username, dag_id, dag_execution_id)

    experiment_id = run_params.get('experiment_id')

    if dag_execution_id:
        lock_key, lock_lease_time = acquire_idle_row_lock(cognito_username, dag_execution_id)
        dag_json, dag_execution_status, auth_info = fetch_dag_execution_info(cognito_username, dag_id, dag_execution_id)
        parent_run_name = dag_execution_status['parent_run_name']
        parent_run_id = dag_execution_status['parent_run_id']
        if not experiment_id and 'experiment_id' in dag_json:
            experiment_id = dag_json['experiment_id']

        if not experiment_id:
            raise('Experiment id not defined')

        dag_name = dag_json['name']

        if dagParamsJsonRuntime and 'recovery' in dagParamsJsonRuntime \
            and dagParamsJsonRuntime['recovery'].lower() == 'true':
            dag_json = override_dag_runtime_params_for_recovery(dag_json, dagParamsJsonRuntime, dag_execution_status)

    else:
        dag_json = dag_utils.fetch_dag_details(cognito_username, dag_id)
        print(dag_json)

        if dagParamsJsonRuntime:
            dag_json = override_dag_runtime_params(dag_json, dagParamsJsonRuntime)

        queue_message_uuid, token = get_custom_token(cognito_username, groups)
        custom_token="Custom {0}:{1}".format(queue_message_uuid, token)
        auth_info = {
                'mlflow_tracking_uri' : run_params.get('MLFLOW_TRACKING_URI'),
                'mlflow_tracking_token': run_params.get('MLFLOW_TRACKING_TOKEN'),
                'mlflow_parallels_uri': run_params.get('MLFLOW_PARALLELS_URI'),
                'custom_token': custom_token,
                'cognito_client_id': service_conf['cognitoClientId']['S']
                }

        dag_name = dag_json['name']
        if not experiment_id:
            if 'experiment_id' in dag_json:
                experiment_id = dag_json['experiment_id']
            else:
                experiment_id = create_and_update_experiment(cognito_username, auth_info, dag_id, dag_name)
        dag_json['experiment_id'] = experiment_id

        dag_execution_id = dag_utils.get_new_dag_exec_id(dag_id)

        #create parent run
        parent_run_name = dag_name + "-" + str(dag_execution_id)
        parent_run_id, parent_artifact_uri, parent_run_status, parent_run_lifecycle_stage \
            = call_create_run(cognito_username, experiment_id, auth_info, parent_run_name,
                              tags={'dag_execution_id': dag_execution_id})

        dag_execution_status = {'parent_run_name': parent_run_name, 'parent_run_id': parent_run_id}

        node_statuses = dict()
        for n in dag_json['nodes']:
            node_statuses[n['id']] = {'status' : 'PENDING'}
        dag_execution_status['nodes'] = node_statuses
        dag_utils.create_dag_execution_record(cognito_username, dag_id, dag_execution_id, dag_execution_status, dag_json, auth_info)

        dag_detail_artifact = {'dag_json': dag_json, 'dag_execution_id': dag_execution_id}
        log_mlflow_artifact(auth_info, parent_run_id, dag_detail_artifact, '.mlflow-parallels', 'dag_details.json.bin')
        lock_key, lock_lease_time = acquire_idle_row_lock(cognito_username, dag_execution_id)

    if httpOperation:
        release_row_lock(lock_key)
        logger.info("Invoke a separate lambda asynchronously and return")
        run_params['username'] = cognito_username
        if groups:
            run_params['groups'] = groups
        if dag_execution_id not in run_params:
            run_params['dag_execution_id'] = dag_execution_id
        client = boto3.client('lambda')
        dag_lambda = service_conf['executeDagLambda']['S']
        client.invoke(FunctionName=dag_lambda,
                      InvocationType='Event',
                      Payload=json.dumps(run_params))
        rv = {'status' : 'success', 'dagExecutionId': dag_execution_id, 'parentRunId': parent_run_id}
        logger.info("A separate lambda invoked, returning http response: " + str(rv))
        return respond(None, rv)

    try:
        incoming_dag_graph, outgoing_graph, node_dict, edge_dict = get_graph_struct(dag_json)
        node_statuses, lock_lease_time = fetch_node_status(cognito_username, auth_info, node_dict, dag_execution_status['nodes'],
                                          lock_key, lock_lease_time)
        dag_execution_status['nodes'] = node_statuses
        allDone, ready_to_run = get_ready_to_run_nodes(incoming_dag_graph, node_statuses)

        print(f'Nodes ready to run {ready_to_run}', "Analyze ready nodes for partitioning")
        modified = perform_node_partitioning(ready_to_run, incoming_dag_graph,
                                             outgoing_graph, node_dict, edge_dict, dag_execution_status)
        if modified:
            new_dag_json = dag_utils.create_new_dag_json(dag_json, node_dict, edge_dict)
            update_ddb_dag_exec_info(cognito_username, new_dag_json, dag_execution_id, dag_execution_status)
            ##Evaluate ready to run nodes again
            allDone, ready_to_run = get_ready_to_run_nodes(incoming_dag_graph, node_statuses)
            dag_json = new_dag_json

        ## Group ready to run nodes by original_node_id
        ## so that nodes that split out of the same node can be launched together
        nodes_group_by_original = {}
        for n in ready_to_run:
            if 'original_node_id' in node_dict[n]:
                orig_node = node_dict[n]['original_node_id']
                if orig_node not in nodes_group_by_original:
                    nodes_group_by_original[orig_node] = []
                nodes_group_by_original[orig_node].append(n)
            else:
                nodes_group_by_original[n] = [n]

        print(f'Nodes ready to run {ready_to_run}')
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            try:
                for orig_node, node_list_to_run in nodes_group_by_original.items():
                    ## All nodes in node_list_to_run are identical except input split,
                    ## Use the first node to get the details of the node specs
                    node_details = node_dict[node_list_to_run[0]]
                    xformname, xform_path, xform_params = get_xform_details(node_details)
                    instance_type = node_details['instanceType']
                    dag_execution_info = {'dagid': dag_id, 'dag_execution_id': dag_execution_id}
                    parallelization = node_details.get('parallelization')
                    k8s_params = node_details.get('k8s_params')
                    ##get all input specs
                    run_input_spec_map = {}
                    for n in node_list_to_run:
                        node_details = node_dict[n]
                        run_name = node_details['name']
                        input_data_spec = get_input_data_spec(n, node_dict[n], dag_execution_status['nodes'], incoming_dag_graph)
                        run_id, artifact_uri, run_status, run_lifecycle_stage = \
                            call_create_run(cognito_username, experiment_id, auth_info, run_name, parent_run_id, xformname)
                        run_input_spec_map[run_id] = input_data_spec
                        run_info = {'run_id': run_id, 'status': run_status, 'artifact_uri': artifact_uri,
                                    'lifecycle_stage': run_lifecycle_stage}
                        dag_execution_status['nodes'][n] = run_info

                    print("Submit bootstrap for node {} to the executor".format(orig_node))
                    launch_future = executor.submit(launch_bootstrap_run_project, cognito_username, orig_node, auth_info,
                                                    run_input_spec_map, artifact_uri, xformname, xform_params,
                                                    experiment_id, frequency, instance_type,
                                                    periodic_run_name, dag_execution_info, xform_path=xform_path,
                                                    parent_run_id=parent_run_id, last_in_chain_of_xforms='False',
                                                    parallelization=parallelization, k8s_params=k8s_params)
                    futures.append((launch_future, n))

                for f, nid in futures:
                    print("Look for future result for node {}".format(nid))
                    f.result(timeout=30)
                    lock_lease_time = renew_lock(lock_key, lock_lease_time)
            except Exception as ex:
                logger.warning("Failure in launching nodes: " + str(ex))
                return respond("Node launch failed", dict())

        update_dag_run_status(cognito_username, dag_execution_id, dag_execution_status)
        rv = {'status' : 'success', 'dagExecutionId': dag_execution_id, 'parentRunId': parent_run_id}
        if allDone:
            update_run(auth_info, parent_run_id, 'FINISHED')
            print('Dag execution Completed Successfully')
        if httpOperation:
            print('Send Http Response')
            print(rv)
            return respond(None, rv)
        else:
            return rv
    finally:
        release_row_lock(lock_key)


def acquire_idle_row_lock(cognito_username, dag_execution_id):
    dag_exec_key = create_dag_execution_key(cognito_username, dag_execution_id)
    locked = lock_utils.acquire_idle_row_lock(DAG_EXECUTION_TABLE, dag_exec_key)
    if not locked:
        print("No lock, cannot proceed")
        raise ("Could not acquire lock, row not idle for too long")

    lock_lease_time = int(time.time())
    return dag_exec_key, lock_lease_time

def release_row_lock(dag_exec_key):
    lock_utils.release_row_lock(DAG_EXECUTION_TABLE, dag_exec_key)

def renew_lock(key, lock_lease_time):
    return lock_utils.renew_lock(DAG_EXECUTION_TABLE, key, lock_lease_time)

def fetch_dag_execution_info(cognito_username, dag_id, dag_execution_id):
    record = dag_utils.get_dag_execution_record(cognito_username, dag_id, dag_execution_id)
    return record['dag_json'], record['run_status'], record['auth_info']

def create_dag_execution_key(cognito_username, dag_execution_id):
    key = dict()
    hk = dict()
    hk['S'] = cognito_username
    key['username'] = hk
    rk = dict()
    rk['S'] = dag_execution_id
    key['dag_execution_id'] = rk
    return key

def update_dag_run_status(cognito_username, dag_execution_id, status):
    client = boto3.client('dynamodb')
    key = create_dag_execution_key(cognito_username, dag_execution_id)

    print('Updating status##')
    print(status)

    now = int(time.time())
    uxp = 'SET run_status = :st, update_time = :ut'
    eav = {
        ":st" : {"S" : json.dumps(status)},
        ":ut" : {"N" : str(now)}
    }

    try:
        client.update_item(TableName=DAG_EXECUTION_TABLE, Key=key, UpdateExpression=uxp,
                       ExpressionAttributeValues=eav)
        return True
    except Exception as ex:
        status_msg = 'caught while updating dag status' + str(ex)
        raise(status_msg)

def get_graph_struct(dag_json):
    """
       Returns adjacency list for graph and
       a map of parameters for each node
    """
    incoming_graph = dict()
    outgoing_graph = dict()
    node_dict = dict()
    for entry in dag_json['nodes']:
        node = entry['id']
        incoming_graph[node] = list()
        outgoing_graph[node] = list()
        node_dict[node] = entry

    edge_dict = {}
    for edge in dag_json['edges']:
        a = edge['source']
        b = edge['target']

        edge_dict[(a,b)] = edge
        incoming_graph[b].append(a)
        outgoing_graph[a].append(b)

    return incoming_graph, outgoing_graph, node_dict, edge_dict

def fetch_node_status(cognito_username, auth_info, node_details, previous_statuses, lock_key, lock_lease_time):
    node_statuses = dict()
    for node in node_details.keys():
        node_run_info = previous_statuses[node]
        node_statuses[node] = node_run_info
        if node_run_info.get('run_id'):
            run_id = node_run_info['run_id']
            status = node_run_info['status']
            if run_id and status == "RUNNING":
                run_info = fetch_run_id_info(auth_info, run_id)
                print('RUN INFO for '+run_id)
                print(run_info)
                node_statuses[node].update(run_info)
                lock_lease_time = renew_lock(lock_key, lock_lease_time)
    return node_statuses, lock_lease_time

def get_ready_to_run_nodes(dag_graph, node_statuses):
    ready_to_run = list()
    failed_run = None
    for node in dag_graph.keys():
        if node_statuses[node]['status'] == 'FAILED':
            failed_run = node_statuses[node]['run_id']
            break
        if node_statuses[node]['status'] != 'PENDING':
            continue
        dependency_nodes = dag_graph[node]
        if not dependency_nodes:
            ready_to_run.append(node)
        else:
            all_dependencies_completed = True
            for n in dependency_nodes:
                if n in node_statuses and node_statuses[n]['status'] != 'FINISHED':
                    all_dependencies_completed = False
                    break
            if all_dependencies_completed:
                ready_to_run.append(node)

    all_done = False
    if failed_run:
        print('Aborting: run-id ' + node_statuses[node]['run_id'] + ' failed')
        return False, []
    elif not ready_to_run:
        all_done = True
        for n in node_statuses.keys():
            if node_statuses[n]['status'] != 'FINISHED':
                all_done = False
                break
        if all_done:
            return True, []
    return all_done, ready_to_run


def get_xform_details(node_details):
    if 'transform' in node_details:
        xformname = node_details['transform']
    else:
        xformname = None
    xform_path = None
    if 'xform_path' in node_details:
        xform_path = node_details['xform_path']
    xform_params = dict()
    if node_details.get('positional'):
        xform_params['positional'] = node_details['positional']
    if node_details.get('kwarg'):
        kv_items = dict()
        for entry in node_details.get('kwarg'):
            key = entry['key']
            val = entry['value']
            kv_items[key] = val
        xform_params['kwargs'] = kv_items
    logger.info("##XFORM_PARAMS##")
    logger.info(xform_params)

    return xformname, xform_path, xform_params


def get_input_data_spec(node, node_details, node_statuses, dag_graph):
    inputs = node_details.get('input')
    if not inputs:
        return None

    input_specs = list()
    for input in inputs:
        spec = dict()
        if 'name' in input:
            spec['name'] = input['name']
        if input['type'] == 'no-input-data':
            continue
        elif input['type'] == 'existing_xform':
            dep_node = input['source']
            spec['type'] = 'mlflow-run-artifacts'
            spec['run_id'] = node_statuses[dep_node]['run_id']
            input_specs.append(spec)
        elif input['type'] == 'mlflow-run-artifacts':
            spec['type'] = 'mlflow-run-artifacts'
            if 'run_id' in input:
                spec['run_id'] = input['run_id']
            elif 'input_run_id' in input:
                spec['run_id'] = input['input_run_id']
            else:
                raise Exception('No run id available')

            if 'prefix' in input:
                spec['prefix'] = input['prefix']
            input_specs.append(spec)
        else:
            spec['type'] = input['type'].lower()
            if input.get('bucketname'):
                spec['bucketname'] = input['bucketname']
            input_specs.append(spec)
            if input.get('pathInBucket'):
                spec['prefix'] = input['pathInBucket']
            elif 'prefix' in input:
                spec['prefix'] = input['prefix']
            else:
                spec['prefix'] = "/"

        if input.get('time_spec'):
            spec['time_spec'] = input['time_spec']

        if 'input_run_id' in input:
            spec['run_id'] = input['input_run_id']

        if 'unsplitted_prefix' in input:
            spec['unsplitted_prefix'] = input['unsplitted_prefix']
        if 'parallelization_schedule' in input:
            spec['parallelization_schedule'] = input['parallelization_schedule']
        if 'partition_keygen' in input:
            spec['partition_keygen'] = input['partition_keygen']

    print("input_data_spec_string = " + str(input_specs))
    return input_specs


def create_and_update_experiment(cognito_username, auth_info, dag_id, dag_name):
    experiment_id = create_experiment(auth_info, dag_name + "-" + dag_id)
    ddb_txns.update_parallel(cognito_username, dag_id, None, None, experiment_id)
    return experiment_id


def override_dag_runtime_params(dag_json, dagParamsJsonRuntime):
    runtime_params_dict = dict()
    for param_node in dagParamsJsonRuntime['node']:
        runtime_params_dict[param_node['id']] = param_node

    for json_node in dag_json['nodes']:
        runtime_param_node = runtime_params_dict[json_node['id']]
        old_inputs = json_node.get('input')
        new_input_list = []
        runtime_user_inputs = runtime_param_node.get('input')
        if runtime_user_inputs and old_inputs:
            for user_input in runtime_user_inputs:
                updated_input = {}
                if not 'type' in user_input:
                    user_input['type'] = 'infinsnap'
                    user_input['time_spec'] = infinsnap()
                if user_input['type'] == 'existing_xform':
                    ##Only parallelization can be changed for existing xform input
                    old_matching_input = get_matching_input(old_inputs, user_input['name'])
                    if not old_matching_input:
                        raise Exception("Graph modified at runtime")
                    updated_input = copy.deepcopy(old_matching_input)
                    if 'partition_params' in user_input \
                            and 'partition_params' in user_input \
                            and 'parallelization' in user_input['partition_params']:
                        updated_input['partition_params']['parallelization'] \
                            = user_input['partition_params']['parallelization']
                    new_input_list.append(updated_input)
                else:
                    if 'type' in user_input:
                        updated_input['type'] = user_input['type']
                    if 'time_spec' in user_input:
                        updated_input['time_spec'] = user_input['time_spec']
                    if 'bucketname' in user_input:
                        updated_input['bucketname'] = user_input['bucketname']
                    if 'pathInBucket' in user_input:
                        updated_input['pathInBucket'] = user_input['pathInBucket']
                    if 'run_id' in user_input:
                        updated_input['run_id'] = user_input['run_id']
                    if 'input_run_id' in user_input:
                        updated_input['input_run_id'] = user_input['input_run_id']
                    if 'partition_params' in user_input:
                        updated_input['partition_params'] = user_input['partition_params']
                    if 'name' in user_input:
                        updated_input['name'] = user_input['name']
                    new_input_list.append(updated_input)
            json_node['input'] = new_input_list
        if 'kwarg' in runtime_param_node:
            json_node['kwarg'] = runtime_param_node['kwarg']
        if 'instanceType' in runtime_param_node:
            json_node['instanceType'] = runtime_param_node['instanceType']
        if 'runlocation' in runtime_param_node:
            json_node['runlocation'] = runtime_param_node['runlocation']
        if 'k8s_params' in runtime_param_node:
            json_node['k8s_params'] = runtime_param_node['k8s_params']
        if 'parallelization' in runtime_param_node:
            json_node['parallelization'] = runtime_param_node['parallelization']
    return dag_json

def override_dag_runtime_params_for_recovery(dag_json, dagParamsJsonRuntime, dag_execution_status):
    """
    Override the dag definition for failure recovery
    :param dag_json: the dag definition during dag execution, it may have splitted nodes
    :param dagParamsJsonRuntime: dag parameters passed for recovery
    :return: updated dag json
    """
    runtime_params_dict = dict()
    for param_node in dagParamsJsonRuntime['node']:
        runtime_params_dict[param_node['id']] = param_node

    for json_node in dag_json['nodes']:
        if 'original_node' in json_node:
            original_node_id = json_node['original_node']
        else:
            original_node_id = json_node['id']
        runtime_param_node = runtime_params_dict[original_node_id]
        if 'kwarg' in runtime_param_node:
            json_node['kwarg'] = runtime_param_node['kwarg']
        if 'instanceType' in runtime_param_node:
            json_node['instanceType'] = runtime_param_node['instanceType']
        if 'runlocation' in runtime_param_node:
            json_node['runlocation'] = runtime_param_node['runlocation']

        run_status = dag_execution_status['nodes'][json_node['id']]
        if run_status['status'] == 'FAILED':
            if 'previous_attempts' not in run_status:
                run_status['previous_attempts'] = list()
            prev_run_id = run_status.pop('run_id')
            run_status['previous_attempts'].append(prev_run_id)
            dag_execution_status['nodes'][json_node['id']] \
                = {'status': 'PENDING', 'previous_attempts': run_status['previous_attempts']}


    return dag_json

def update_ddb_dag_exec_info(cognito_username, dag_json, dag_execution_id, dag_exec_status):
    client = boto3.client('dynamodb')

    dag_exec_key = create_dag_execution_key(cognito_username, dag_execution_id)

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


def perform_node_partitioning(ready_to_run, incoming_edge_graph, outgoing_edge_graph,
                              node_dict, edge_dict, dag_execution_status):
    modified = False
    for ready_node in ready_to_run:
        node_info = node_dict[ready_node]
        inputs = node_info.get('input')
        parallelization = int(node_info.get('parallelization', 1))
        if parallelization <= 1:
            return None, None, False
        if not inputs:
            return

        new_node_ids = []
        for index in range(parallelization):
            ##Deep copy entire node_info
            new_node_info = copy.deepcopy(node_info)
            new_node_info['original_node_id'] = node_info['id']
            new_node_info['id'] = node_info['id'] + '-part-' + str(index + 1)
            new_node_ids.append(new_node_info['id'])
            node_dict[new_node_info['id']] = new_node_info
            dag_execution_status['nodes'][new_node_info['id']] = {'status': 'PENDING'}

        for index, nd in enumerate(new_node_ids):
            updated_inputs = copy.deepcopy(inputs)
            ##TODO Add a check to ensure that only one input name has partitioned configured.
            for current_input in updated_inputs:
                if 'partition_params' in current_input:
                    current_input['parallelization_schedule'] = ['default', parallelization, index]
                    if 'partitioner' in current_input['partition_params']:
                        if current_input['partition_params']['partitioner'] == 'custom':
                            current_input['partition_keygen'] = current_input['partition_params']['lambda']
                        else:
                            current_input['partition_keygen'] = current_input['partition_params']['partitioner']
                    current_input.pop('partition_params')
            node_dict[nd]['input'] = updated_inputs

        node_dict.pop(ready_node)
        modified = True
        # Update edges
        perform_edge_split(ready_node, new_node_ids, edge_dict, node_dict,
                           incoming_edge_graph, outgoing_edge_graph)
    return modified

def perform_edge_split(old_node, new_node_ids, edge_dict, node_dict, incoming_edge_graph, outgoing_edge_graph):
    for newn in new_node_ids:
        incoming_edge_graph[newn] = []
        outgoing_edge_graph[newn] = []

    #Split incoming edges
    if old_node in incoming_edge_graph:
        source_nodes = incoming_edge_graph.pop(old_node)
        for srcn in source_nodes:
            old_edge = (srcn, old_node)
            edge_dict.pop(old_edge)
            for newn in new_node_ids:
                new_edge = (srcn, newn)
                edge_dict[new_edge] = {'source':srcn, 'target': newn}
                incoming_edge_graph[newn].append(srcn)

    #Split outgoing_edges
    if old_node in outgoing_edge_graph:
        target_nodes = outgoing_edge_graph.pop(old_node)
        for tgtn in target_nodes:
            old_edge = (old_node, tgtn)
            edge_dict.pop(old_edge)
            for newn in new_node_ids:
                new_edge = (newn, tgtn)
                edge_dict[new_edge] = {'source':newn, 'target': tgtn}
                outgoing_edge_graph[newn].append(tgtn)
            ##Need to change inputs of the target node.
            if 'input' in node_dict[tgtn]:
                one_existing_xform_input = None
                for one_input in node_dict[tgtn]['input']:
                    if one_input['type'] == 'existing_xform' and one_input["source"] == old_node:
                        one_input["source"] = new_node_ids[0]
                        one_existing_xform_input = one_input
                        break
                for newn in new_node_ids[1:]:
                    new_existing_xform_input = copy.deepcopy(one_existing_xform_input)
                    new_existing_xform_input['source'] = newn
                    node_dict[tgtn]['input'].append(new_existing_xform_input)


def infinsnap(snaptime=datetime.now()):
    # add timezone info to naive snaptime
    if (snaptime.tzinfo == None or snaptime.tzinfo.utcoffset(snaptime) == None):
        snaptime = snaptime.replace(tzinfo=datetime.now(timezone.utc).astimezone().tzinfo)
    snaptime = snaptime.astimezone(timezone.utc)
    return snaptime.strftime('tm%Y%m%d%H%M%S')


def get_matching_input(input_list, name):
    for input in input_list:
        if input['name'] == name:
            return input
    return None


def launch_bootstrap_run_project(
        cognito_username, orig_node, auth_info, run_input_spec_map, artifact_uri, xformname,
        xform_params, experiment_id, frequency, instance_type,
        periodic_run_name, dag_execution_info,
        xform_path=None, parent_run_id=None, last_in_chain_of_xforms='False',
        parallelization=None, k8s_params=None):
    logger.info("RUN_ID -> INPUT_SPEC #")
    logger.info(str(run_input_spec_map))
    logger.info(artifact_uri)
    pdst = urlparse(artifact_uri)
    bucket_name = pdst.netloc
    if (pdst.path[0] == '/'):
        path_in_bucket = pdst.path[1:]
    else:
        path_in_bucket = pdst.path

    #Call run-project
    body = dict()
    body['MLFLOW_TRACKING_URI'] = auth_info.get('mlflow_tracking_uri')
    body['MLFLOW_TRACKING_TOKEN'] = auth_info.get('mlflow_tracking_token')
    body['MLFLOW_PARALLELS_URI'] = auth_info.get('mlflow_parallels_uri')
    body['project_files_bucket'] = bucket_name
    body['project_files_path_in_bucket'] = path_in_bucket
    body['run_id'] = parent_run_id
    body['parent_run_id'] = parent_run_id
    body['experiment_id'] = experiment_id
    body['last_in_chain_of_xforms'] = last_in_chain_of_xforms
    body['instance_type'] = instance_type
    body['original_node'] = orig_node
    if periodic_run_name:
        body['periodic_run_name'] = periodic_run_name
    if dag_execution_info:
        body['dagid'] = dag_execution_info['dagid']
        body['dag_execution_id'] = dag_execution_info['dag_execution_id']

    if parallelization:
        body['parallelization'] = parallelization

    ddt = period_run.calculate_drop_dead_time(frequency)
    if (ddt):
        body['drop_dead_time'] = ddt
    if run_input_spec_map:
        body['run_input_spec_map'] = json.dumps(run_input_spec_map)
    if xformname:
        body['xformname'] = xformname
    if xform_path:
        body['xform_path'] = xform_path

    params = {}
    if xform_params.get('kwargs'):
        params.update(xform_params.get('kwargs'))
    ##TODO Handle positional arguments
    body['params'] = params

    if k8s_params:
        body.update(k8s_params)

    run_project_event = dict()
    run_project_event['body'] = json.dumps(body)
    run_project_event['requestContext'] = create_request_context(cognito_username)
    run_project_event['httpMethod'] = 'POST'

    response = run_project.run_project(run_project_event, None)

    logger.info("Response ##")
    logger.info(response)
    return response['body']
