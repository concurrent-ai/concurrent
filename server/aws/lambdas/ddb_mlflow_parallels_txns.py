import logging
import time
from botocore.exceptions import ClientError
from utils import get_ddb_boto3_client_parallels
import ddb_mlflow_parallels_queries as ddb_parallel_utils


logger = logging.getLogger()
logger.setLevel(logging.INFO)


##############################################################
## Insert and Update Transactions for Parallels
###############################################################

def add_user_urole_for_parallel(username, userid, parallel_id, role_str):
    table_name, version, client = get_ddb_boto3_client_parallels(username)

    hash_key_urole = ddb_parallel_utils.get_hash_key_urole(userid)
    range_key_urole = ddb_parallel_utils.get_range_key_urole_parallel(version, parallel_id)

    hash_key_parallelrole = ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)
    range_key_parallel_role = ddb_parallel_utils.get_range_key_parallelrole_user(version, userid)
    return add_ugrole_txn_internal(client, table_name, hash_key_urole,
                                   range_key_urole, hash_key_parallelrole,
                                   range_key_parallel_role, role_str)


def add_group_role_for_parallel(username, groupid, parallel_id, role_str):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    hash_key_grole = ddb_parallel_utils.get_hash_key_grole(groupid)
    range_key_grole = ddb_parallel_utils.get_range_key_urole_parallel(version, parallel_id)

    hash_key_parallelrole = ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)
    range_key_parallel_role = ddb_parallel_utils.get_range_key_parallelrole_group(version, groupid)
    return add_ugrole_txn_internal(client, table_name, hash_key_grole,
                                   range_key_grole, hash_key_parallelrole,
                                   range_key_parallel_role, role_str)


def remove_user_role_for_parallel(cognito_username, userid, parallel_id):
    table_name, version, client = get_ddb_boto3_client_parallels(cognito_username)
    hash_key_urole = ddb_parallel_utils.get_hash_key_urole(userid)
    range_key_urole = ddb_parallel_utils.get_range_key_urole_parallel(version, parallel_id)

    hash_key_prole = ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)
    range_key_prole = ddb_parallel_utils.get_range_key_parallelrole_user(version, userid)

    delete_urole_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': hash_key_urole},
                'range_key': {'S': range_key_urole}
            }
        }
    }
    delete_pinfo_role_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': hash_key_prole},
                'range_key': {'S': range_key_prole}
            }
        }
    }
    client.transact_write_items(TransactItems=[delete_urole_txn, delete_pinfo_role_txn])


def remove_group_role_for_parallel(cognito_username, groupid, parallel_id):
    table_name, version, client = get_ddb_boto3_client_parallels(cognito_username)
    hash_key_grole = ddb_parallel_utils.get_hash_key_grole(groupid)
    range_key_grole = ddb_parallel_utils.get_range_key_grole_parallel(version, parallel_id)

    hash_key_prole = ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)
    range_key_prole = ddb_parallel_utils.get_range_key_parallelrole_group(version, groupid)

    delete_urole_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': hash_key_grole},
                'range_key': {'S': range_key_grole}
            }
        }
    }
    delete_pinfo_role_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': hash_key_prole},
                'range_key': {'S': range_key_prole}
            }
        }
    }
    client.transact_write_items(TransactItems=[delete_urole_txn, delete_pinfo_role_txn])


def create_new_parallel(username, group_list, parallel_id,
                   parallel_name, dag_json, description, creator_uid):
    table_name, version, client = get_ddb_boto3_client_parallels(username)

    parallelinfo_hash_key = ddb_parallel_utils.get_hash_key_parallelinfo()
    parallelinfo_range_key = ddb_parallel_utils.get_range_key_parallelinfo(version, parallel_id)

    creation_time = str(int(time.time() * 1000))
    txn_list = []
    parallelinfo_txn = {
        'Put': {
            'TableName': table_name,
            'Item': {
                 'hash_key': {'S': parallelinfo_hash_key},
                 'range_key': {'S': parallelinfo_range_key},
                 'parallel_name': {'S': parallel_name},
                 'parallel_json': {'S': dag_json},
                 'creator': {'S': creator_uid},
                 'creation_time': {'S': creation_time},
                 'update_time': {'S': creation_time}
            },
            'ConditionExpression': 'attribute_not_exists(range_key)',
            'ReturnValuesOnConditionCheckFailure': 'NONE'
        }
    }
    if description:
        parallelinfo_txn['Put']['Item']['description'] = {'S' : description}
    txn_list.append(parallelinfo_txn)

    parallelname_hash_key = ddb_parallel_utils.get_hash_key_parallelname()
    parallelname_range_key = ddb_parallel_utils.get_range_key_parallelname(version, parallel_name)
    name_txn = {
        'Put': {
            'TableName': table_name,
            'Item': {
                'hash_key': {'S': parallelname_hash_key},
                'range_key': {'S': parallelname_range_key},
                'parallel_id': {'S': parallel_id},
            },
            'ConditionExpression': 'attribute_not_exists(hash_key)',
            'ReturnValuesOnConditionCheckFailure': 'NONE'
        }
    }
    txn_list.append(name_txn)

    ##Add manager role for the creator
    urole_txn = {
        'Put': {
            'TableName': table_name,
            'Item': {
                'hash_key': {'S': ddb_parallel_utils.get_hash_key_urole(creator_uid)},
                'range_key': {'S': ddb_parallel_utils.get_range_key_urole_parallel(version, parallel_id)},
                'role': {'S' : 'manager'}
            }
        }
    }
    txn_list.append(urole_txn)

    ##Add role information in parallelinfo as well
    parallelinfo_role_txn = {
        'Put': {
            'TableName': table_name,
            'Item': {
                'hash_key': {'S': ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)},
                'range_key': {'S': ddb_parallel_utils.get_range_key_parallelrole_user(version, creator_uid)},
                'role': {'S': 'manager'}
            }
        }
    }
    txn_list.append(parallelinfo_role_txn)

    if group_list:
        for group in group_list:
            grole_parallel_txn = [
                {
                    'Put': {
                        'TableName': table_name,
                        'Item': {
                            'hash_key': {'S': ddb_parallel_utils.get_hash_key_grole(group)},
                            'range_key': {'S': ddb_parallel_utils.get_range_key_grole_parallel(version, parallel_id)},
                            'role': {'S': 'reader'}
                        }
                    }
                },
                {
                    'Put': {
                        'TableName': table_name,
                        'Item': {
                            'hash_key': {'S': ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)},
                            'range_key': {'S': ddb_parallel_utils.get_range_key_parallelrole_group(version, group)},
                            'role': {'S': 'reader'}
                        }
                    }
                }
            ]
            txn_list = txn_list + grole_parallel_txn

    try:
        client.transact_write_items(TransactItems=txn_list)
        logger.info('create_new_parallel: successfully created new parallel id '
                    + str(parallel_id))
    except ClientError as e:
        logger.info("Potentially a condition check error")
        logger.info(str(e))
        raise e
    except Exception as ex:
        logger.error('Failed to create parallel {0} with id {1} '.format(parallel_name, parallel_id) + str(ex))
        raise ex


def update_parallel(username, parallel_id, dag_json, description, experiment_id):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    parallelinfo_hash_key = ddb_parallel_utils.get_hash_key_parallelinfo()
    parallelinfo_range_key = ddb_parallel_utils.get_range_key_parallelinfo(version, parallel_id)

    update_strings = []
    eav = {}

    if description:
        update_strings.append("description = :desc")
        eav[':desc'] = {'S': description}
    if dag_json:
        update_strings.append("parallel_json = :dj")
        eav[':dj'] = {'S': dag_json}
    if experiment_id:
        update_strings.append("experiment_id = :ei")
        eav[':ei'] = {'S': experiment_id}

    if update_strings:
        update_time = str(int(time.time() * 1000))
        update_strings.append("update_time = :ut")
        eav[':ut'] = {'S': update_time}
    else:
        ##Nothing to do
        return

    update_expr = "set " + ", ".join(update_strings)

    txn_list = []
    parallelinfo_txn = {
        'Update': {
            'TableName': table_name,
            'Key': {
                 'hash_key': {'S': parallelinfo_hash_key},
                 'range_key': {'S': parallelinfo_range_key}
            },
            'UpdateExpression': update_expr,
            'ExpressionAttributeValues': eav
        }
    }
    print("Update Txn: " + str(parallelinfo_txn))

    txn_list.append(parallelinfo_txn)

    ##Execute update parallel
    try:
        client.transact_write_items(TransactItems=txn_list)
        logger.info('update_parallel: successfully updated parallel id '
                    + str(parallel_id))
    except ClientError as e:
        logger.info("Potentially a condition check error")
        logger.info(str(e))
        raise e
    except Exception as ex:
        logger.error('Failed to update parallel {0} with id {1} '.format(parallel_id) + str(ex))
        raise ex


def rename_parallel(username, parallel_id, old_name, parallel_name):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    parallelinfo_hash_key = ddb_parallel_utils.get_hash_key_parallelinfo()
    parallelinfo_range_key = ddb_parallel_utils.get_range_key_parallelinfo(version, parallel_id)

    txn_list = []
    parallelinfo_txn = {
        'Update': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': parallelinfo_hash_key},
                'range_key': {'S': parallelinfo_range_key}
            },
            'UpdateExpression': 'set parallel_name = :pn',
            'ExpressionAttributeValues': {
                ':pn': {'S': parallel_name}
            }
        }
    }
    txn_list.append(parallelinfo_txn)

    parallelname_hash_key = ddb_parallel_utils.get_hash_key_parallelname()
    parallelname_range_key = ddb_parallel_utils.get_range_key_parallelname(version, parallel_name)
    name_txn = {
        'Put': {
            'TableName': table_name,
            'Item': {
                'hash_key': {'S': parallelname_hash_key},
                'range_key': {'S': parallelname_range_key},
                'parallel_id': {'S': parallel_id},
            },
            'ConditionExpression': 'attribute_not_exists(hash_key)',
            'ReturnValuesOnConditionCheckFailure': 'NONE'
        }
    }
    txn_list.append(name_txn)

    oldname_hash_key = ddb_parallel_utils.get_hash_key_parallelname()
    oldname_range_key = ddb_parallel_utils.get_range_key_parallelname(version, old_name)
    old_name_delete_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': oldname_hash_key},
                'range_key': {'S': oldname_range_key}
            }
        }
    }
    txn_list.append(old_name_delete_txn)

    ##Execute rename transactions
    try:
        client.transact_write_items(TransactItems=txn_list)
        logger.info('rename_parallel: successfully renamed parallel id '
                    + str(parallel_id))
    except ClientError as e:
        logger.info("Potentially a condition check error")
        logger.info(str(e))
        raise e
    except Exception as ex:
        logger.error('Failed to rename parallel {0} with id {1} '.format(parallel_id) + str(ex))
        raise ex


def delete_parallel(username, parallel_id, parallel_name, users, groups):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    txn_list = []
    name_hash_key = ddb_parallel_utils.get_hash_key_parallelname()
    name_range_key = ddb_parallel_utils.get_range_key_parallelname(version, parallel_name)
    old_name_delete_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': name_hash_key},
                'range_key': {'S': name_range_key}
            }
        }
    }
    txn_list.append(old_name_delete_txn)

    parallelinfo_hash_key = ddb_parallel_utils.get_hash_key_parallelinfo()
    parallelinfo_range_key = ddb_parallel_utils.get_range_key_parallelinfo(version, parallel_id)
    parallelinfo_txn = {
        'Delete': {
            'TableName': table_name,
            'Key': {
                'hash_key': {'S': parallelinfo_hash_key},
                'range_key': {'S': parallelinfo_range_key}
            }
        }
    }
    txn_list.append(parallelinfo_txn)

    ##Delete user auths
    for user in users:
        urole_txn = {
            'Delete': {
                'TableName': table_name,
                'Key': {
                    'hash_key': {'S': ddb_parallel_utils.get_hash_key_urole(user)},
                    'range_key': {'S': ddb_parallel_utils.get_range_key_urole_parallel(version, parallel_id)}
                }
            }
        }
        txn_list.append(urole_txn)

        parallelinfo_role_txn = {
            'Delete': {
                'TableName': table_name,
                'Key': {
                    'hash_key': {'S': ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)},
                    'range_key': {'S': ddb_parallel_utils.get_range_key_parallelrole_user(version, user)}
                }
            }
        }
        txn_list.append(parallelinfo_role_txn)

    ##Delete group auths
    if groups:
        for group in groups:
            grole_parallel_txn = [
                {
                    'Delete': {
                        'TableName': table_name,
                        'Key': {
                            'hash_key': {'S': ddb_parallel_utils.get_hash_key_grole(group)},
                            'range_key': {'S': ddb_parallel_utils.get_range_key_grole_parallel(version, parallel_id)}
                        }
                    }
                },
                {
                    'Delete': {
                        'TableName': table_name,
                        'Key': {
                            'hash_key': {'S': ddb_parallel_utils.get_hash_key_parallelrole(parallel_id)},
                            'range_key': {'S': ddb_parallel_utils.get_range_key_parallelrole_group(version, group)}
                        }
                    }
                }
            ]
            txn_list = txn_list + grole_parallel_txn

    ##Execute delete transactions
    try:
        client.transact_write_items(TransactItems=txn_list)
        logger.info('delete_parallel: successfully deleted parallel id '
                    + str(parallel_id))
    except Exception as ex:
        logger.error('Failed to delete parallel {0} with id {1} '.format(parallel_id) + str(ex))
        raise ex


def set_parallel_tags(username, parallel_id, tag_str):
    table_name, version, client = get_ddb_boto3_client_parallels(username)
    key = dict()
    hk = dict()
    hk['S'] = ddb_parallel_utils.get_hash_key_parallelinfo()
    key['hash_key'] = hk
    rk = dict()
    rk['S'] = ddb_parallel_utils.get_range_key_parallelinfo(version, parallel_id)
    key['range_key'] = rk

    eav = dict()
    tg = dict()
    tg['S'] = tag_str
    eav[':tg'] = tg

    upd = 'set tags = :tg'

    try:
        client.update_item(TableName=table_name, Key=key, \
                           UpdateExpression=upd, ExpressionAttributeValues=eav)
    except Exception as ex:
        logger.info(str(ex))
        raise ex

############################ Private Methods ##################################################
def add_ugrole_txn_internal(client, table_name, hash_key_ugrole, range_key_ugrole, hash_key_resource_role,
                            range_key_resource_role, role_str):

    transcation_items = []
    ugrole_entry = {
        'Put' : {
            'TableName' : table_name,
            'Item' : {
                'hash_key' : { 'S' : hash_key_ugrole},
                'range_key' : { 'S' : range_key_ugrole},
                'role' : { 'S' : role_str }
            },
            'ReturnValuesOnConditionCheckFailure' : 'NONE'
        }
    }
    resourcelrole_entry = {
        'Put': {
            'TableName': table_name,
            'Item': {
                'hash_key': {'S': hash_key_resource_role},
                'range_key': {'S': range_key_resource_role},
                'role': {'S': role_str}
            },
            'ReturnValuesOnConditionCheckFailure': 'NONE'
        }
    }
    transcation_items.append(ugrole_entry)
    transcation_items.append(resourcelrole_entry)

    try:
        client.transact_write_items(TransactItems=transcation_items)
    except Exception as ex:
        logger.error(ex)
        raise ex

