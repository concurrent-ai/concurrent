import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_periodic_run_info(cognito_username, periodic_run_name):
    client = boto3.client('dynamodb')

    table_name = os.environ['PERIODIC_RUNS_TABLE']

    key = dict()
    hk = dict()
    hk['S'] = cognito_username
    key['username'] = hk
    rk = dict()
    rk['S'] = periodic_run_name
    key['periodicRunName'] = rk

    try:
        pr_result = client.get_item(TableName=table_name, Key=key)
    except Exception as ex:
        status_msg = 'caught while get_periodic_run_info' + str(ex)
        logger.info(status_msg)
        return False, status_msg, dict()

    if 'Item' in pr_result:
        item = pr_result['Item']
        this_expr = dict()
        this_expr['periodic_run_name'] = periodic_run_name
        this_expr['json'] = item['periodicRunJson']
        this_expr['custom_token'] = item['customToken']
        return True, '', this_expr
    else:
        return False, 'No such entry', dict()

## Test
if __name__ == "__main__":
    status, status_msg, entry = get_periodic_run_info("isstage5", "titanic_weekly")
    print(status, status_msg, entry)
