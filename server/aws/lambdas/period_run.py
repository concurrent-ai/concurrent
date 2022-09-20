import json
import sys
import os
import io
import logging
import time
from datetime import datetime, timezone
import re
from os.path import sep
import tempfile
import sysconfig

import boto3
import requests
from requests.exceptions import HTTPError

from utils import get_service_conf, create_request_context
from periodic_run_utils import get_periodic_run_info
from transform_utils import get_xform_info, make_short_name

import dag_utils, execute_dag

from urllib.parse import urlparse
from mlflow_utils import call_create_run
import run_project 

logger = logging.getLogger()
logger.setLevel(logging.INFO)

verbose = True

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


def period_run(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    item = event
    periodic_run_id = item['periodic_run_id']
    logger.info('periodic_run_id=' + str(periodic_run_id))
    username = item['username']
    customCustomerId = item['customCustomerId']
    logger.info('username=' + str(username))
    logger.info('customCustomerId=' + str(customCustomerId))
    cognito_username = username

    success, status, periodic_run = get_periodic_run_info(cognito_username, periodic_run_id)

    if (success == False):
        logger.error("No periodic run found for id "+str(periodic_run_id))
        return respond(ValueError('Could not find periodic run '
                                  + periodic_run_id + ', err=' + status))

    success, status, service_conf = get_service_conf()
    if (success == False):
        err = 'period_run: Error {0} lookup service conf'.format(status)
        logger.error(err)
        return respond(ValueError(err))

    logger.info(periodic_run)
    periodic_run_info = json.loads(periodic_run['json']['S'])

    frequency = periodic_run_info.get('period').get('type')
    experiment_id = periodic_run_info['experiment_id']
    cognito_client_id = service_conf['cognitoClientId']['S']
    custom_token = None
    if 'custom_token' in periodic_run:
        custom_token = periodic_run['custom_token']['S']
    auth_info = {
            'mlflow_tracking_uri' : periodic_run_info.get('MLFLOW_TRACKING_URI'),
            'mlflow_tracking_token': periodic_run_info.get('MLFLOW_TRACKING_TOKEN'),
            'mlflow_parallels_uri': periodic_run_info.get('MLFLOW_PARALLELS_URI'),
            'custom_token': custom_token,
            'cognito_client_id': cognito_client_id
            }

    ##Handle Dags
    if 'dagid' in periodic_run_info:
        if 'data' in periodic_run_info:
            data = periodic_run_info['data']
        else:
            data = None
        print("Periodic execution of dag for dagid " + periodic_run_info['dagid'])
        launch_dag(cognito_username, periodic_run_name, periodic_run_info['dagid'], experiment_id,
                auth_info, frequency, data)
        return
    else:
        data = periodic_run_info['data']

    ##Continue with periodic transform execution
    transform_list = periodic_run_info['transforms']
    xformname = transform_list[0]['transform_name']
    run_target = periodic_run_info['runtarget']
    input_params = periodic_run_info.get('params')
    xform_params = dict()
    if input_params.get('positional'):
        xform_params['positional'] = input_params['positional']
    if input_params.get('kwargs'):
        kv_items = dict()
        for entry in input_params.get('kwargs'):
            key = entry['key']
            val = entry['value']
            kv_items[key] = val
        xform_params['kwargs'] = kv_items
    logger.info("##XFORM_PARAMS##")
    logger.info(xform_params)

    num_of_xforms = len(transform_list)

    if num_of_xforms > 1:
        ##Create Parent Run
        parent_run_name = periodic_run['periodic_run_name']
        parent_run_id, parent_artifact_uri, parent_run_status, parent_run_lifecycle_stage \
            = call_create_run(cognito_username, experiment_id, auth_info, parent_run_name)
    else:
        parent_run_id = None

    ## create run_id
    run_id, artifact_uri, run_status, run_lifecycle_stage = call_create_run(
        cognito_username, experiment_id, auth_info, xformname, parent_run_id)
    dag_detail_artifact = {'dag_json': json.dumps({'testk1': 'testv1'}), 'dag_execution_id': 'blah-blah'}

    instance_type = run_target['instance_type']
    periodic_run_name = periodic_run['periodic_run_name']

    input_data_spec = None
    if data['type'] != 'no-input-data':
        input_data_spec = get_input_data_spec(data, frequency)

    launch_run_project(cognito_username, auth_info, run_id, artifact_uri, xformname,
        xform_params, experiment_id, frequency, instance_type,
        input_data_spec, periodic_run_name, None, parent_run_id, 0)

    if num_of_xforms > 1:
        previous_run_id = run_id
        index = 1
        for txform in transform_list[1:]:
            index = index + 1
            last_in_chain_of_xforms = 'False'
            if index == num_of_xforms:
                ##Set this flag for the last transform
                ##to ensure parent run is marked as completed
                last_in_chain_of_xforms = 'True'
            #Create a new runid
            txformname = txform['transform_name']
            run_id, artifact_uri, run_status, run_lifecycle_stage = call_create_run(
                cognito_username, experiment_id, auth_info, txformname, parent_run_id)
            input_data_spec = {"type": "mlflow-run-artifacts", "run_id": previous_run_id}
            input_data_spec_str = get_input_data_spec_string(input_data_spec)
            launch_run_project(cognito_username, auth_info, run_id, artifact_uri, txformname,
                               {}, experiment_id, frequency, instance_type,
                               input_data_spec_str, periodic_run_name, None, parent_run_id,
                               last_in_chain_of_xforms)
            previous_run_id = run_id
    return

def launch_dag(cognito_username, periodic_run_name, dagid, experiment_id, auth_info,
        frequency, data):
    print('periodic dag execution')
    dag_json = dag_utils.fetch_dag_details(cognito_username, dagid)

    dag_json = execute_dag.update_dag_to_handle_input_partitioners(dag_json)

    #dag may already have an experiment id but for periodic run,
    #we use the experiment id assigned to the periodic run
    dag_json['experiment_id'] = experiment_id

    dag_execution_id = dag_utils.get_new_dag_exec_id(dagid)
    # create parent run
    parent_run_name = dag_json['name'] + "-" + periodic_run_name
    parent_run_id, parent_artifact_uri, parent_run_status, parent_run_lifecycle_stage \
        = call_create_run(cognito_username, experiment_id, auth_info, parent_run_name)

    dag_execution_status = {'parent_run_name': parent_run_name, 'parent_run_id': parent_run_id}
    node_statuses = dict()
    for n in dag_json['nodes']:
        node_statuses[n['id']] = {'status': 'PENDING'}
        for node_input in n['input']:
            input_type = node_input['type'].lower()
            if input_type == 'infinsnap' or input_type == 'infinslice':
                if not data:
                    input_data = {'type': input_type, 'bucket': node_input['bucketname'],
                                  'path_in_bucket': get_path_prefix(node_input)}
                else:
                    ##TODO: get bucket and input for each node
                    input_data = data
                input_spec_object = get_input_data_spec_object(input_data, frequency)
                node_input['time_spec'] =  input_spec_object['time_spec']
                print('Updated Spec: ', node_input)
    dag_execution_status['nodes'] = node_statuses
    dag_utils.create_dag_execution_record(cognito_username, dagid, dag_execution_id, dag_execution_status, dag_json)

    #Invoke execute_dag
    dag_event = dict()
    dag_event['username'] = cognito_username
    dag_event['dagid'] = dagid
    dag_event['dag_execution_id'] = dag_execution_id
    dag_event['periodic_run_name'] = periodic_run_name
    dag_event['experiment_id'] = experiment_id
    dag_event['frequency'] = frequency
    return execute_dag.execute_dag(dag_event, None)


def get_path_prefix(node_input):
    if 'pathInBucket' in node_input:
        return node_input['pathInBucket']
    elif 'prefix' in node_input:
        return node_input['prefix']
    else:
        raise('No prefix specified')


def launch_run_project(
        cognito_username, auth_info, run_id, artifact_uri, xformname,
        xform_params, experiment_id, frequency, instance_type,
        input_data_spec, periodic_run_name, dag_execution_info,
        xform_path=None, parent_run_id=None, last_in_chain_of_xforms='False',
        parallelization=None, partition_launch_params = None, k8s_params=None):
    logger.info("RUN_ID #")
    logger.info(run_id)
    logger.info(artifact_uri)
    pdst = urlparse(artifact_uri)
    bucket_name = pdst.netloc
    if (pdst.path[0] == '/'):
        path_in_bucket = pdst.path[1:]
    else:
        path_in_bucket = pdst.path

##    #Store conda env file, and dockerfile into the project directory
##    success, status, xform_info = get_xform_info(cognito_username, xformname)
##    if (success == False):
##        err = "period run: Error {0} in get_xform_info".format(status)
##        logger.error(err)
##        return respond(ValueError(err))
##
##    logger.info(xform_info)
##    conda_env = xform_info.get('conda_env')
##    dockerfile = xform_info.get('dockerfile')
##    xformcode = xform_info.get('xformcode')
##
##    localdir = tempfile.mkdtemp()
##
##    xformcode_file = make_short_name(xformname)+".py"
##    if xformcode:
##        write_file(localdir, xformcode_file, xformcode['S'])
##    else:
##        err = "xform code not found"
##        logger.error(err)
##        return respond(err)
##
##    if conda_env:
##        write_file(localdir, "conda.yaml", conda_env['S'])
##        if not input_data_spec:
##            write_mlflow_project_file_no_input_spec(localdir, xformcode_file, xform_params)
##        else:
##            write_mlflow_project_with_input_spec(localdir, xformname, xform_params)
##    elif dockerfile:
##        write_file(localdir, "dockerfile", dockerfile['S'])
##        ##MLproject is created when docker image is built in rclocal
##    else:
##        err = "No conda environment or dockerfile specified"
##        logger.error(err)
##        return respond(err)
##
##    upload_objects(cognito_username, bucket_name, path_in_bucket + '/.mlflow-parallels/project_files', localdir)

    #Call run-project
    body = dict()
    body['MLFLOW_TRACKING_URI'] = auth_info.get('mlflow_tracking_uri')
    body['MLFLOW_TRACKING_TOKEN'] = auth_info.get('mlflow_tracking_token')
    body['MLFLOW_PARALLELS_URI'] = auth_info.get('mlflow_parallels_uri')
    body['project_files_bucket'] = bucket_name
    body['project_files_path_in_bucket'] = path_in_bucket
    body['run_id'] = run_id
    body['experiment_id'] = experiment_id
    if parent_run_id:
        body['parent_run_id'] = parent_run_id
    body['last_in_chain_of_xforms'] = last_in_chain_of_xforms
    body['instance_type'] = instance_type
    if periodic_run_name:
        body['periodic_run_name'] = periodic_run_name
    if dag_execution_info:
        body['dagid'] = dag_execution_info['dagid']
        body['dag_execution_id'] = dag_execution_info['dag_execution_id']

    if parallelization:
        body['parallelization'] = parallelization

    ddt = calculate_drop_dead_time(frequency)
    if (ddt):
        body['drop_dead_time'] = ddt
    if input_data_spec:
        body['input_data_spec'] = input_data_spec
    if xformname:
        body['xformname'] = xformname
    if xform_path:
        body['xform_path'] = xform_path

    params = {}
    if xform_params.get('kwargs'):
        params.update(xform_params.get('kwargs'))
    ##TODO Handle positional arguments
    body['params'] = params

    if partition_launch_params:
        body['partition_params'] = partition_launch_params

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

def write_file(dir, file_name, content):
    with open(dir + sep + file_name, "w") as fh:
        fh.write(content)

def write_mlflow_project_file_no_input_spec(projdir, xformcode_file, xform_params):
    with open(projdir + sep + 'MLproject', "w") as projfile:
        projfile.write('Name: run-' + xformcode_file + '\n')
        projfile.write('conda_env: conda.yaml\n')
        projfile.write('\n')
        projfile.write('entry_points:' + '\n')
        projfile.write('  main:' + '\n')
        cmd_str = '    command: "python {0}'.format(xformcode_file)
        if xform_params:
            positional_args = xform_params.get("positional")
            if positional_args:
                for arg in positional_args:
                    cmd_str = cmd_str + " " + arg
            kwargs = xform_params.get('kwargs')
            if kwargs:
                for key, value in kwargs.items():
                    cmd_str = cmd_str + " --" + key + "=" + value
        cmd_str = cmd_str + '"\n'
        projfile.write(cmd_str)

def write_mlflow_project_with_input_spec(projdir, xformname, xform_params):
    with open(projdir + sep + 'MLproject', "w") as projfile:
        kwp = ''
        kwargs = xform_params.get('kwargs')
        if kwargs:
            for key, value in kwargs.items():
                kwp = kwp + (' --' + key + '={' + key + '}')
        else:
            kwargs = dict()
        projfile.write('Name: run-' + make_short_name(xformname) + '\n')
        projfile.write('conda_env: conda.yaml\n')
        projfile.write('\n')
        projfile.write('entry_points:' + '\n')
        projfile.write('  main:' + '\n')
        projfile.write('    parameters:\n')
        projfile.write('      service: string\n')
        projfile.write('      input_data_spec: string\n')
        projfile.write('      xformname: string\n')
        for key, value in kwargs.items():
            projfile.write('      ' + key + ': string\n')
        projfile.write(
            '    command: "python -c \'from infinstor import mlflow_run; mlflow_run.main()\'\
                    --input_data_spec={input_data_spec} --service={service}\
                    --xformname={xformname}' + kwp + '"\n')

def get_input_data_spec(data, frequency):
    spec = get_input_data_spec_object(data, frequency)
    return get_input_data_spec_string(spec)

def get_input_data_spec_object(data, frequency):
    input_data_spec = dict()
    input_data_spec['type'] = data['type']
    input_data_spec['bucketname'] = data['bucket']
    # the 'prefix' should not start with a '/' to avoid a double slash in the output artifact object key in s3, like 's3://bucketname/.../infinstor//logs/stdout-stderr.txt'.  
    # Note that, code injected by Run > Transform does not have a leading '/' for the 'prefix' in input_data_spec={prefix: xxxxx}
    # also the code infinstor/__init__.py::get_mlflow_run_artifacts_info(), which generates the 'prefix' in input_data_spec={prefix: xxxxx}, for mlflow run artifacts as input, does a lstrip('/') on the path 
    input_data_spec['prefix'] = data['path_in_bucket'].lstrip('/')  
    ts, formatted_ts = get_current_timestamp()
    if data['type'] == 'infinsnap':
        infin_timestamp = "tm{0}".format(formatted_ts)
    elif data['type'] == 'infinslice':
        last_run_ts = get_last_run_timestamp(ts, frequency, data.get('slice'))
        infin_timestamp = "tm{0}-tm{1}".format(last_run_ts, formatted_ts)
    else:
        raise Exception("Invalid type of data source specified")
    input_data_spec['time_spec'] = infin_timestamp

    logger.info('input_data_spec#')
    logger.info(input_data_spec)
    return input_data_spec

def get_input_data_spec_string(input_data_spec):
    return json.dumps(input_data_spec)

def get_current_timestamp():
    ts = time.time()
    return ts, datetime.fromtimestamp(ts).strftime('%Y%m%d%H%M%S')

def get_last_run_timestamp(ts, frequency, slice=None):
    if (frequency == 'hourly'):
        last_period_ts = ts - 60*60
    elif (frequency == 'daily'):
        last_period_ts = ts - 24 * 60 * 60
    elif (frequency == 'weekly'):
        last_period_ts = ts - 7*24*60*60
    elif (frequency == 'monthly'):
        dt = datetime.fromtimestamp(ts)
        if (dt.month == 1):
            newDt = dt.replace(month=12, year=dt.year - 1)
        else:
            newDt = dt.replace(month=dt.month - 1)
        last_period_ts = newDt.timestamp()
    elif (frequency == 'yearly'):
        dt = datetime.fromtimestamp(ts)
        last_period_ts = dt.replace(year=dt.year - 1).timestamp()
    elif (frequency == 'once'):
        print("Last run doesn't make sense for frequency 'once'")
        raise Exception("Last run doesn't make sense for frequency 'once'")
    else:
        raise Exception("Invalid frequency: "+frequency)

    if slice:
        print('slice = '+str(slice) + '%')
        last_ts = ts - int (((ts - last_period_ts) * slice) / 100)
    else:
        last_ts = last_period_ts

    return datetime.fromtimestamp(last_ts).strftime('%Y%m%d%H%M%S')


# drop_dead_time is the utc time in seconds since 1/1/1970 when
# all xforms for this periodic run must drop dead
def calculate_drop_dead_time(frequency):
    dt = datetime.utcnow()
    if (frequency == 'hourly'):
        rv = (dt - datetime(1970, 1, 1)).total_seconds()+(60*60)
        rv_dt = datetime.fromtimestamp(rv)
        logger.info('calculate_drop_dead_time: hourly. now='
                + dt.strftime("%m/%d/%Y, %H:%M:%S")
                + ', drop_dead_time=' + rv_dt.strftime("%m/%d/%Y, %H:%M:%S"))
        return rv
    elif (frequency == 'daily'):
        rv = (dt - datetime(1970, 1, 1)).total_seconds()+(24*60*60)
        rv_dt = datetime.fromtimestamp(rv)
        logger.info('calculate_drop_dead_time: daily. now='
                + dt.strftime("%m/%d/%Y, %H:%M:%S")
                + ', drop_dead_time=' + rv_dt.strftime("%m/%d/%Y, %H:%M:%S"))
        return rv
    elif (frequency == 'weekly'):
        rv = (dt - datetime(1970, 1, 1)).total_seconds()+(7*24*60*60)
        rv_dt = datetime.fromtimestamp(rv)
        logger.info('calculate_drop_dead_time: weekly. now='
                + dt.strftime("%m/%d/%Y, %H:%M:%S")
                + ', drop_dead_time=' + rv_dt.strftime("%m/%d/%Y, %H:%M:%S"))
        return rv
    elif (frequency == 'monthly'):
        if (dt.month == 12):
            newDt = dt.replace(month=1, year=dt.year + 1)
        else:
            newDt = dt.replace(month=dt.month + 1)
        rv = (newDt - datetime(1970, 1, 1)).total_seconds()
        rv_dt = datetime.fromtimestamp(rv)
        logger.info('calculate_drop_dead_time: montly. now='
                + dt.strftime("%m/%d/%Y, %H:%M:%S")
                + ', drop_dead_time=' + rv_dt.strftime("%m/%d/%Y, %H:%M:%S"))
        return rv
    elif (frequency == 'yearly'):
        newDt = dt.replace(year=dt.year + 1)
        rv = (newDt - datetime(1970, 1, 1)).total_seconds()
        rv_dt = datetime.fromtimestamp(rv)
        logger.info('calculate_drop_dead_time: yearly. now='
                + dt.strftime("%m/%d/%Y, %H:%M:%S")
                + ', drop_dead_time=' + rv_dt.strftime("%m/%d/%Y, %H:%M:%S"))
        return rv
    else:
        logger.info('calculate_drop_dead_time: not setting up')
        return None

# Test
if __name__ == "__main__":
    event = dict()
    event['httpMethod'] = 'POST'
    claims = {'principalId' : 'isstage5'}
    claims['aud'] = "unknown"
    request_context = {'authorizer': claims}
    event['requestContext'] = request_context
    event['body'] = json.dumps({'periodic_run_id' : 'titanic_weekly'})
    period_run(event, "")
