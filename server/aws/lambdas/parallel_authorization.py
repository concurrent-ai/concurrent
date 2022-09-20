import os
import logging
import json
import casbin
from casbin.model import Model

from utils import get_cognito_user
import ddb_mlflow_parallels_txns as ddb_ptxns
import ddb_mlflow_parallels_queries as ddb_pqrs
import casbin
from casbin.model import Model
from casbin import persist

logger = logging.getLogger()
logger.setLevel(logging.INFO)

owner_enforcer = None
explicit_enforcers = dict()
cached_is_authorization_enabled = None


explicit_conf_text = '''
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = (r.sub.name == p.sub) && keyMatch(r.obj.name, p.obj) && regexMatch(r.act, p.act)
'''

cached_is_authorization_enabled = None
explicit_enforcers = dict()

reader_role = [
        # reader role permissions
            'parallel/get'
    ]

editor_role = reader_role + [
    'parallel/update',
    'parallel/rename'
]

manager_role = editor_role + [
    'parallel/delete'
]


role_dict = dict()
role_dict['reader'] = reader_role
role_dict['editor'] = editor_role
role_dict['manager'] = manager_role


def update_cached_is_authorization_enabled(cognito_username):
    global cached_is_authorization_enabled
    if (cached_is_authorization_enabled == None):
        try:
            status = ddb_pqrs.get_authorization_status(cognito_username)
        except Exception as ex:
            logger.warning(str(ex))
            cached_is_authorization_enabled = False
            return
        if status:
            if (status.lower() == 'true' or status.lower() == 'yes'):
                cached_is_authorization_enabled = True
            else:
                cached_is_authorization_enabled = False
        else:
            cached_is_authorization_enabled = False


# returns True|False
def is_authorization_enabled(cognito_username):
    update_cached_is_authorization_enabled(cognito_username)
    global cached_is_authorization_enabled
    return cached_is_authorization_enabled


# returns True|False
def set_is_authorization_enabled(cognito_username, value_to_set):
    # flush cache first
    global cached_is_authorization_enabled
    cached_is_authorization_enabled = None
    return ddb_pqrs.set_authorization_status(cognito_username, value_to_set)


def authorization_error(error_msg: str=None):
    """ returns a dict containing http response details for authorization error: http status code, http response body, http response headers..

    Args:
        error_msg (str, optional): [description]. Defaults to None.

    Returns:
        [dict]: dict containing http response details: http status code, http response body, http response headers..
    """
    return {
            'statusCode': '405',
            'body': 'Permission Denied. Please contact your administrator' + (': ' + error_msg if error_msg else ''),
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Methods': '*',
                'Access-Control-Allow-Credentials': '*'
            },
        }


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


def add_parallel_authorization(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))
    cognito_username, groups = get_cognito_user(event)
    item = json.loads(event['body'])
    logger.info('payload item=' + str(item))
    parallel_id = item['parallel_id']

    if ('principal_type' in item):
        principal_type = item['principal_type']
        if (principal_type != 'user' and principal_type != 'group'):
            return respond('principal_type must be user or group')
    else:
        return respond('principal_type must be present')

    if ('principal_name' in item):
        principal_name = item['principal_name']
    else:
        return respond('principal_name must be present')

    if ('role' in item):
        role = item['role']
    else:
        return respond('role must be present')
    if (not role in ['reader', 'editor', 'manager', 'no-perms']):
        return respond('role must be reader, editor or manager')

    logger.info('parallel_id=' + str(parallel_id) + ', princ=' + str(principal_name)
            + ', type=' + str(principal_type) + ', role=' + str(role))

    #TODO
    # authorized = authorize_parallel_access(cognito_username, groups, parallel_id, 'parallel_roles/set')
    # if not authorized:
    #     emsg = 'get_parallel: {0} not authorized'.format(cognito_username)
    #     logger.info(emsg)
    #     return authorization_error(emsg)

    try:
        if role == 'no-perms':
            if principal_type == 'user':
                ddb_ptxns.remove_user_role_for_parallel(cognito_username, principal_name, parallel_id)
            elif principal_type == 'group':
                ddb_ptxns.remove_group_role_for_parallel(cognito_username, principal_name, parallel_id)
        else:
            if principal_type == 'user':
                ddb_ptxns.add_user_urole_for_parallel(cognito_username, principal_name, parallel_id, role)
            elif principal_type == 'group':
                ddb_ptxns.add_group_role_for_parallel(cognito_username, principal_name, parallel_id, role)
    except Exception as ex:
        msg = "Caught " + str(ex) + " while setting authorization for parallel " + parallel_id
        logger.info(msg)
        return respond(ValueError(msg))

    try:
        roles_info = ddb_pqrs.get_parallel_roles(cognito_username, parallel_id)
    except Exception as ex:
        msg = 'add_parallel_authorization: caught while updating explicit perms ' + str(ex)
        logger.info(msg)
        return respond(ValueError(msg))

    logger.info('Done. Returning=' + str(roles_info))
    rv = dict()
    rv['parallel_authorization'] = get_policy_array(roles_info)
    return respond(None, rv)


def get_parallel_authorization(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)

    operation = event['httpMethod']
    if (operation != 'GET'):
        return respond(ValueError('Unsupported method ' + str(operation)))
    cognito_username, groups = get_cognito_user(event)
    qs = event['queryStringParameters']
    logger.info(qs)

    if ('parallel_id' in qs):
        parallel_id = qs['parallel_id']
    else:
        logger.info("Error: parallel_id not specified")
        return respond(ValueError('parallel_id must be specified'))

    #TODO
    # authorized = authorize_parallel_access(cognito_username, groups, parallel_id, 'parallel_roles/get')
    # if not authorized:
    #     emsg = 'get_parallel: {0} not authorized'.format(cognito_username)
    #     logger.info(emsg)
    #     return authorization_error(emsg)

    try:
        role_info = ddb_pqrs.get_parallel_roles(cognito_username, parallel_id)
    except Exception as ex:
        msg = 'caught while get_parallel_roles' + str(ex)
        logger.info(msg)
        return respond(ValueError(msg))

    res = get_policy_array(role_info)

    rv = dict()
    rv['parallel_authorization'] = res
    return respond(None, rv)


def get_policy_array(role_info:dict):
    """

    Args:
        role_info (dict): similar to below
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

    Returns:
        list: returns a list of policies with format
        { 'principal_name':<group_name>|<user_name>,
          'principal_type':'user'|'group',
          'role':<role>
        }
    """
    outa = []
    for user, role in role_info['user_roles'].items():
        outa.append({'principal_name': user, 'principal_type': 'user', 'role': role})
    for group, role in role_info['group_roles'].items():
        outa.append({'principal_name': group, 'principal_type': 'group', 'role': role})
    return outa


def read_parallel_authorization_from_ddb(cognito_username, parallel_id):
    try:
        roles = ddb_pqrs.get_parallel_roles(cognito_username, parallel_id)
    except Exception as ex:
        logger.warning("Caught " + str(ex) + " while reading parallel auth for " + str(parallel_id))
        return []

    return get_policy_array(roles)


def convert_array_to_policy_line(prefix, mthds):
    """
    returns "<prefix> ( <method1> ) | ( <method2> ) | ...
    for example "p, user:ds0,      12, experiments/create|experiments/delete"

    args:
        prefix: similar to
            "p, user:ds0,      12, "
            "p, group:dsgroup, 12, "
        mthds: methods for a role, similar to experiments/create, experiments/delete, ...
    """
    return prefix + ' (' + ')|('.join(mthds) + ')'


class StringAdapter(persist.Adapter):
    _policy_string = ""

    def __init__(self, policy_string):
        self._policy_string = policy_string

    def load_policy(self, model):
        for line in self._policy_string.splitlines():
            logger.info('StringAdapter: adding policy line ' + line.strip())
            persist.load_policy_line(line.strip(), model)


class ArrayOfDictAdapter(persist.Adapter):
    # Example: [{"principal_name": "ds0", "principal_type": "user", "role": "manager"},
    #           {"principal_name": "ds1", "principal_type": "user", "role": "manager"}]
    _policy_array = ""
    _model_id = ""

    def __init__(self, model_id, policy_array):
        """[summary]

        Args:
            model_id (str): the id of the model
            policy_array (list[dict]): similar to below
              [ {"principal_name": "ds0", "principal_type": "user", "role": "manager"},
                {"principal_name": "ds1", "principal_type": "user", "role": "manager"} ]
                {"principal_name": "dsgroup", "principal_type": "group", "role": "manager"} ]

        """
        self._model_id = model_id
        self._policy_array = policy_array

    def load_policy(self, model):
        for oe in self._policy_array:
            # line like
            # "p, user:ds0,      12, "
            # "p, group:dsgroup, 12, "
            prefix = 'p, ' + oe['principal_type'] + ':' + oe['principal_name'] \
                     + ', ' + self._model_id + ', '
            global role_dict
            line = convert_array_to_policy_line(prefix, role_dict[oe['role']])
            logger.info('ArrayOfDictAdapter: adding policy line ' + line)
            persist.load_policy_line(line, model)


def check_authorization(cognito_username:str, groups, parallel_id, act):

    logger.info('check_authorization: Entered. cognito_username=' + str(cognito_username)
            + ', groups=' + str(groups) + ', parallel_id=' + str(parallel_id)
            + ', act=' + str(act))

    # if authorization is disabled on the server side
    if (not is_authorization_enabled(cognito_username)):
        logger.info('check_authorization: authorization not enabled. returning True')
        return True

    # explicit perms check
    global explicit_enforcers
    if (not parallel_id in explicit_enforcers):
        pl = read_parallel_authorization_from_ddb(cognito_username, parallel_id)
        logger.info('policy for ' + str(parallel_id) + ' = ' + str(pl))
        if (pl):
            explicit_model = Model()
            explicit_model.load_model_from_text(explicit_conf_text)
            explicit_adapter = ArrayOfDictAdapter(parallel_id, pl)
            explicit_enforcers[parallel_id] = casbin.Enforcer(model=explicit_model,
                adapter=explicit_adapter)
    if (parallel_id in explicit_enforcers):
        ea = explicit_enforcers[parallel_id]
        if (ea):
            obj = {'name': parallel_id}
            sub = {'name': 'user:' + cognito_username}
            if (ea.enforce(sub, obj, act)):
                logger.info('check_authorization: explicit_enforcer for user returns True')
                return True
            for group in groups:
                sub = {'name': 'group:' + group}
                if (ea.enforce(sub, obj, act)):
                    logger.info('check_authorization: explicit_enforcer for group returns True')
                    return True
    errmsg:str = 'check_authorization: returning False by default'
    logger.info(errmsg)
    return False
