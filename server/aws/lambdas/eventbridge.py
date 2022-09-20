
import json
import os
import logging
import boto3
from botocore.exceptions import ClientError
import time
import tempfile
import uuid
import urllib.parse
import re

from utils import get_service_conf, get_subscriber_info, get_cognito_user, get_custom_token
from kubernetes import client, config, dynamic
from kubernetes.client import models as k8s
from kubernetes.client import api_client, Configuration
from kubernetes.client.rest import ApiException

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

def del_periodicrun(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)
    success, status, subs = get_subscriber_info(cognito_username) 
    
    success, status, service_conf = get_service_conf()

    body = event['body']
    print('body=' + str(body))
    bdict = urllib.parse.parse_qs(body)
    if not 'periodicRuns' in bdict:
        err = 'add_mod_periodicrun: Error. must specify periodicRun(s) to delete'
        logger.error(err)
        return respond(ValueError(err))
    for pr in bdict['periodicRuns']:
        prs = pr.split(',')
        for one_pr in prs:
            delete_one_pr(one_pr, cognito_username)
    return respond(None, {})

def delete_one_pr(pr, cognito_username):
    # first delete sqs q
    # next delete rule in eventbridge
    events_client = boto3.client("events")
    massaged_name = replace_bad_chars(cognito_username + '-' + pr)
    try:
        print('delete_one_pr: removing target for ' + massaged_name + ' user ' + cognito_username)
        res = events_client.remove_targets(
                Rule=massaged_name,
                Ids=['PeriodicRunHandler'],
                Force=True
            )
    except Exception as ex:
        msg = 'While removing target, caught ' + str(ex)
        print(msg)
    try:
        print('delete_one_pr: deleting rule ' + massaged_name + ' of user ' + cognito_username)
        res = events_client.delete_rule(Name=massaged_name, Force=True)
    except Exception as ex:
        msg = 'While deleting rule, caught ' + str(ex)
        print(msg)
    # finally, delete run from our ddb table
    ddb_client = boto3.client("dynamodb")
    try:
        res = ddb_client.delete_item(
                TableName=os.environ['PERIODIC_RUNS_TABLE'],
                Key={
                        'username': {'S': cognito_username},
                        'periodicRunName': {'S': pr}
                    }
                )
    except ClientError as e:
        msg = 'While removing ddb entry, caught ' + e.response['Error']['Message']\
            + ' during put_item'
        print(msg)

def add_mod_periodicrun(event, context):
    logger.info('## ENVIRONMENT VARIABLES')
    logger.info(os.environ)
    logger.info('## EVENT')
    logger.info(event)
    logger.info("Received event: " + json.dumps(event, indent=2))

    operation = event['httpMethod']
    if (operation != 'POST'):
        return respond(ValueError('Unsupported method ' + str(operation)))

    cognito_username, groups = get_cognito_user(event)
    success, status, subs = get_subscriber_info(cognito_username) 
    
    success, status, service_conf = get_service_conf()

    body = event['body']
    print('body=' + str(body))
    bdict = urllib.parse.parse_qs(body)
    if not 'periodicRunName' in bdict or not 'periodicRunJson' in bdict:
        err = 'add_mod_periodicrun: Error. periodicRunName and periodicRunJson must be specified'
        logger.error(err)
        return respond(ValueError(err))

    periodic_run_name = bdict['periodicRunName'][0]
    periodic_run_json = bdict['periodicRunJson'][0]
    print('periodicRunName=' + str(periodic_run_name))
    print('periodicRunJson=' + periodic_run_json)

    #Inject Parallels token in the ddb entry
    queue_message_uuid, token = get_custom_token(cognito_username, groups)
    custom_token="Custom {0}:{1}".format(queue_message_uuid, token)

    item={
        'username': {'S': cognito_username},
        'periodicRunName': {'S': periodic_run_name},
        'periodicRunJson': {'S': periodic_run_json},
        'customToken': {'S': custom_token}
        }

    ddb_client = boto3.client("dynamodb")
    try:
        res = ddb_client.put_item(
                TableName=os.environ['PERIODIC_RUNS_TABLE'],
                Item=item,
                ReturnValues='NONE'
                )
    except ClientError as e:
        msg = 'Caught ' + e.response['Error']['Message'] + ' during put_item'
        print(msg)
        return respond(ValueError(msg))

    events_client = boto3.client("events")
    massaged_name = replace_bad_chars(cognito_username + '-' + periodic_run_name)
    print('massaged=' + massaged_name)

    periodic_run_j = json.loads(periodic_run_json)
    sch = periodic_run_j['period']
    tss = sch['value']
    tss_split = tss.split('_')

    c_e_b = CronExpressionBuilder(sch['type'])
    cron_expr = c_e_b.set_minute(tss_split[0])\
                    .set_hour(tss_split[1])\
                    .set_day(tss_split[2])\
                    .set_month(tss_split[3])\
                    .set_week(tss_split[4])\
                    .set_year(tss_split[5])\
                    .build()
    print('cron_expr=' + cron_expr)

    try:
        res = events_client.put_rule(Name=massaged_name, ScheduleExpression=cron_expr)
    except Exception as ex:
        msg = 'Caught ' + str(ex)
        print(msg)
        return respond(ValueError(msg))

    time.sleep(1)

    try:
        res = events_client.put_targets(
                Rule=massaged_name,
                Targets=[
                    {
                        'Id': 'PeriodicRunHandler',
                        'Arn': service_conf['periodRunLambdaArn']['S'],
                        'Input': '{'
                            + '"customCustomerId" : "' + subs['customerId']['S'] + '", '
                            + '"username" : "' + cognito_username + '", '
                            + '"periodic_run_id" : "' + periodic_run_name + '"'
                            + '}'
                    }
                ]
            )
    except Exception as ex:
        msg = 'Caught ' + str(ex)
        print(msg)
        return respond(ValueError(msg))
    return respond(None, {})

def replace_bad_chars(inp):
    return re.sub('[^0-9a-zA-Z_\.\-]+', '-', inp)

class CronExpressionBuilder():
    def __init__(self, typ):
        self.typ = typ
        self.hour = '*'
        self.minute = '*'
        self.day = '*'
        self.month = '*'
        self.week = '?'
        self.year = '*'

    def build(self):
        return 'cron(' + self.minute + ' ' + self.hour + ' ' + self.day + ' '\
                + self.month + ' ' + self.week + ' ' + self.year + ')'

    def set_minute(self, minute):
        self.minute = minute
        return self

    def set_hour(self, hour):
        if not self.typ == 'hourly':
            self.hour = hour
        return self

    def set_day(self, day):
        if self.typ == 'monthly' or self.typ == 'once' or self.typ == 'yearly':
            self.day = day
        elif self.typ == 'weekly':
            self.day = '?'
        return self

    def set_month(self, month):
        if self.typ == 'once' or self.typ == 'yearly':
            self.month = month
        return self

    def set_week(self, week):
        if self.typ == 'weekly':
            week_days_inputs = week.split(',')
            week_val = ''
            for i in range(len(week_days_inputs)):
                if i > 0:
                    week_val = (week_val + ',')
                w = int(week_days_inputs[i])
                week_val = week_val + str(w + 1)
                self.week = week_val
        return self

    def set_year(self, year):
        if self.typ == 'once':
            self.year = year
        return self
