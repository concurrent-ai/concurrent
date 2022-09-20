import logging
import os
import tempfile
import sys
import base64
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_xform_info(cognito_username, xformname):
    if xformname == 'no-op':
        #Special transform
        return get_noop_xform()
    elif (xformname.find(':') != -1): # if xformname contains :, it is a git URL
        return get_xform_info_git(cognito_username, xformname)
    else:
        return get_xform_info_ddb(cognito_username, xformname)

def get_xform_info_git(cognito_username, xformname):
    dst_dir = tempfile.mkdtemp()
    from dulwich import porcelain
    porcelain.clone(xformname, dst_dir)

    dockerfile_str = ''
    try:
        with open(os.path.join(dst_dir, 'Dockerfile'), 'r') as dockerfile:
            dockerfile_str = dockerfile.read()
    except:
        logger.info('get_xform_info_git: xformname=' + xformname + ', no dockerfile')

    condayaml_str = ''
    try:
        with open(os.path.join(dst_dir, 'conda.yaml'), 'r') as condayamlfile:
            condayaml_str = condayamlfile.read()
    except:
        logger.info('get_xform_info_git: xformname=' + xformname + ', no conda.yaml')

    xformcode_str = ''
    try:
        with open(os.path.join(dst_dir, 'xformcode.py'), 'r') as xformcodefile:
            xformcode_str = xformcodefile.read()
    except:
        logger.info('get_xform_info_git: xformname=' + xformname + ', no xformcode.py')

    this_expr = dict()
    this_expr['xformname'] = xformname
    this_expr['conda_env'] = {'S': condayaml_str}
    this_expr['dockerfile'] = {'S': dockerfile_str}
    this_expr['xformcode'] = {'S': xformcode_str}
    return True, '', this_expr

def get_xform_info_ddb(cognito_username, xformname):
    client = boto3.client('dynamodb')

    table_name = os.environ['XFORMS_TABLE']

    key = dict()
    hk = dict()
    hk['S'] = cognito_username
    key['username'] = hk
    rk = dict()
    rk['S'] = xformname
    key['xformname'] = rk

    try:
        pr_result = client.get_item(TableName=table_name, Key=key)
    except Exception as ex:
        status_msg = 'caught while get_xform_info 1 ' + str(ex)
        logger.info(status_msg,exc_info=sys.exc_info())
        return False, status_msg, dict()

    if 'Item' in pr_result:
        # Found xform in user's name
        item = pr_result['Item']
        this_expr = dict()
        this_expr['xformname'] = xformname
        this_expr['conda_env'] = item.get('conda_env')
        this_expr['dockerfile'] = item.get('dockerfile')
        this_expr['xformcode'] = item.get('xformcode')
        # if xform_local_files_zip is not empty/None
        if item.get('xform_local_files_zip'): 
            # convert the bytestream to base64 bytestream; then convert base64 bytestream to a str
            this_expr['xform_local_files_zip'] = base64.b64encode( item.get('xform_local_files_zip').get('B') ).decode('ascii')
        # if xform_local_files_zip_filelist is not empty/None
        if item.get('xform_local_files_zip_filelist'): 
            this_expr['xform_local_files_zip_filelist'] = item.get('xform_local_files_zip_filelist').get('S')
        return True, '', this_expr

    hk['S'] = '-'
    try:
        pr_result = client.get_item(TableName=table_name, Key=key)
    except Exception as ex:
        status_msg = 'caught while get_xform_info 2 ' + str(ex)
        logger.info(status_msg,exc_info=sys.exc_info())
        return False, status_msg, dict()

    if 'Item' in pr_result:
        # Found xform in name '-', i.e. available to all users
        item = pr_result['Item']
        this_expr = dict()
        this_expr['xformname'] = xformname
        this_expr['conda_env'] = item.get('conda_env')
        this_expr['dockerfile'] = item.get('dockerfile')
        this_expr['xformcode'] = item.get('xformcode')
        this_expr['xform_local_files_zip'] = item.get('xform_local_files_zip')
        this_expr['xform_local_files_zip_filelist'] = item.get('xform_local_files_zip_filelist')
        return True, '', this_expr
    else:
        return False, 'No such entry', dict()

def make_short_name(xformname):
    if (xformname.find(':') != -1):
        return 'git_xform'
    else:
        return xformname

def get_partitioner_info(cognito_username, partition_func):
    client = boto3.client('dynamodb')

    table_name = os.environ['PARTITIONER_TABLE']

    key = dict()
    hk = dict()
    hk['S'] = cognito_username
    key['owner'] = hk
    rk = dict()
    rk['S'] = partition_func
    key['partitioner_name'] = rk

    try:
        pr_result = client.get_item(TableName=table_name, Key=key)
    except Exception as ex:
        status_msg = 'caught while get_partitioner_info 1 ' + str(ex)
        logger.info(status_msg)
        return False, status_msg, dict()

    if 'Item' in pr_result:
        # Found xform in user's name
        item = pr_result['Item']
        this_expr = dict()
        this_expr['partitioner_name'] = partition_func
        this_expr['code'] = item['code']['S']
        return True, '', this_expr

    hk['S'] = 'infinstor'
    try:
        pr_result = client.get_item(TableName=table_name, Key=key)
    except Exception as ex:
        status_msg = 'caught while get_partitioner_info 1 ' + str(ex)
        logger.info(status_msg)
        return False, status_msg, dict()

    if 'Item' in pr_result:
        # Found xform in user's name
        item = pr_result['Item']
        this_expr = dict()
        this_expr['partitioner_name'] = partition_func
        this_expr['code'] = item['code']['S']
        return True, '', this_expr
    else:
        return False, 'No such entry', dict()


def get_directory_partitioner_info():
    info = dict()
    info['partitioner_name'] = 'directory'
    with open('directory_partitioner.py') as ofd:
        partitioner_code = ofd.read()
    info['code'] = partitioner_code
    return True, '', info


def get_noop_xform():
    noop_info = dict()
    noop_info['xformname'] = 'no-op'
    noop_info['xformcode'] = {'S': 'print("This should not be executed")'}
    with open('noop.dockerfile') as ofd:
        docker_env = ofd.read()
    noop_info['dockerfile'] = {'S': docker_env}
    return True, '', noop_info
