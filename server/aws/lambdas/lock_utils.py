import boto3
import time

def acquire_row_lock(table, key):
    client = boto3.client('dynamodb')
    now = int(time.time())
    uxp = 'SET locked = :lock, update_time = :ut'

    condition = 'locked = :nolock'
    eav = {
        ":nolock" : {"S" : "no"} ,
        ":lock" : {"S": "yes"},
        ":ut": {"N":str(now)}
    }

    try:
        client.update_item(TableName=table, Key=key, UpdateExpression=uxp,
                           ConditionExpression=condition, ExpressionAttributeValues=eav)
        print("Lock acquired for key " + str(key) + " at " + str(now))
        return True
    except Exception as ex:
        print ("Couldn't acquire lock")
        return False

def release_row_lock(table, key):
    client = boto3.client('dynamodb')
    now = int(time.time())
    uxp = 'SET locked = :nolock, update_time = :ut'

    condition = 'locked = :lock'
    eav = {
        ":nolock" : {"S" : "no"} ,
        ":lock" : {"S": "yes"},
        ":ut": {"N":str(now)}
    }

    try:
        client.update_item(TableName=table, Key=key, UpdateExpression=uxp,
                           ConditionExpression=condition, ExpressionAttributeValues=eav)
        print("Lock released for key " + str(key) + "at " + str(now))
        return True
    except Exception as ex:
        print ("Couldn't release lock")
        raise(ex)

def force_release_row_lock(table, key):
    client = boto3.client('dynamodb')
    now = int(time.time())
    uxp = 'SET locked = :nolock, update_time = :ut'

    eav = {
        ":nolock" : {"S" : "no"},
        ":ut": {"N":str(now)}
    }

    try:
        client.update_item(TableName=table, Key=key, UpdateExpression=uxp,
                           ExpressionAttributeValues=eav)
        print("Force-released lock for key " + str(key) + " at " + str(now))
        return True
    except Exception as ex:
        print ("Couldn't release lock")
        raise(ex)

def acquire_idle_row_lock(table, key, idle=120, max_wait=300):
    ### Acquire lock if no updates for 'idle' number of seconds
    if acquire_row_lock(table, key):
        return True

    total_wait_time = 0
    sleep_time = 30
    print('wait for lock to get released')
    while total_wait_time < max_wait:
        time.sleep(sleep_time)
        last_update_time = get_update_time(table, key)
        now = int(time.time())
        if now - last_update_time > idle:
            print('Lock is idle, force release the lock.')
            print('last update time = ' + str(last_update_time) +", now = "+ str(now))
            force_release_row_lock(table, key)
            return acquire_row_lock(table, key)
        else:
            total_wait_time = total_wait_time+sleep_time
    ## Still no lock, give up
    print('Failed to acquire lock: give up')
    return False

def get_update_time(table, key):
    client = boto3.client('dynamodb')
    ret = client.get_item(TableName=table, Key=key, AttributesToGet=["update_time"])
    return int(ret['Item']['update_time']['N'])

def renew_lock(table, lock_key, lock_lease_time):
    now = int(time.time())
    if now - lock_lease_time < 30:
        #No need to renew
        return lock_lease_time
    else:
        client = boto3.client('dynamodb')
        uxp = 'SET update_time = :ut'
        eav = {
            ":ut": {"N": str(now)}
        }
        try:
            client.update_item(TableName=table, Key=lock_key, UpdateExpression=uxp,
                               ExpressionAttributeValues=eav)
            print("Renewed lock for key " + str(lock_key) + "at " + str(now))
            return now
        except Exception as ex:
            print("Couldn't renew lock")
            raise (ex)