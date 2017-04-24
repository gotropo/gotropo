from lambda_signals.signals import lambda_handler
import boto3
from botocore.exceptions import ClientError

def get_s3_client(region_name):
    return boto3.client("s3", region_name = region_name)

def process_event(event, context):
    return dict(
        stack_id      = event['StackId'],
        resource_name = event['LogicalResourceId'],
        #physical_name = event.get('PhysicalResourceId'),
        stack_name    = event['ResourceProperties']['StackName'],
        aws_region    = event['ResourceProperties']['AwsRegion'],
        bucket_name   = event['ResourceProperties']['BucketName'],
        s3_prefix     = event['ResourceProperties']['Prefix'],
        s3_suffix     = event['ResourceProperties']['Suffix'],
        lambda_arn    = event['ResourceProperties']['LambdaARN'],
    )

def trigger_name(event_details):
    return event_details['stack_id']+":"+event_details['resource_name']

def trigger_config(event_details):
    return dict(
        Id = trigger_name(event_details),
        LambdaFunctionArn = event_details['lambda_arn'],
        Events = [
            's3:ObjectCreated:*'
         ],
        Filter=dict(
            Key=dict(
                FilterRules =
                [
                    dict(
                        Name  = 'Prefix',
                        Value = event_details['s3_prefix']
                    ),
                    dict(
                        Name  = 'Suffix',
                        Value = event_details['s3_suffix']
                    ),
                ]
            )
        )
    )

def get_current_notifications(event_details):
    s3 = get_s3_client(event_details['aws_region'])
    notifications = dict()
    response = s3.get_bucket_notification_configuration(Bucket = event_details['bucket_name'])

    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise("Get current notification events error: HTTP status code != 200")

    for conf in ['TopicConfigurations','QueueConfigurations']:
        if response.get(conf):
            notifications[conf] = response[conf]
    notifications['LambdaFunctionConfigurations'] = response.get('LambdaFunctionConfigurations', [])

    return notifications

def put_notifications(event_details, notifications, set_physical_resource_id = True):
    s3 = get_s3_client(event_details['aws_region'])
    print("Set notification:")
    print(notifications)
    response = s3.put_bucket_notification_configuration(
        Bucket = event_details['bucket_name'],
        NotificationConfiguration = notifications,
    )
    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        if set_physical_resource_id:
            return (True, dict(PhysicalResourceId = trigger_name(event_details)))
        else:
            return (True, dict())
    else:
        raise("Error updating or creating notifications")

def find_trigger(event_details, lambda_notif_configs):
    print("Looking for trigger id:")
    print(trigger_name(event_details))
    print("In triggers:")
    print(lambda_notif_configs)
    for count, n in enumerate(lambda_notif_configs):
        print("comparing to:")
        print(n['Id'])
        if n['Id'] == trigger_name(event_details):
            print("Found at:")
            print(count)
            return count
    print("NOT FOUND")
    return None

def create_resource(event, context):
    #get current events
    #append to trigger list
    event_details = process_event(event, context)
    notifications = get_current_notifications(event_details)
    notifications['LambdaFunctionConfigurations'].append(trigger_config(event_details))
    #TODO: check for duplicate Ids in LambdaFunctionConfigurations
    return put_notifications(event_details, notifications)

def update_resource(event, context):
    #get current events
    event_details = process_event(event, context)
    notifications = get_current_notifications(event_details)
    #look for id==trigger_name in list
    current_trigger_index = find_trigger(event_details, notifications['LambdaFunctionConfigurations'])
    if current_trigger_index is not None:
        #replace trigger in list (which is the same object as in notifications dict)
        notifications['LambdaFunctionConfigurations'][current_trigger_index] = trigger_config(event_details)
    else:
        #Config not in list. Assume issue with adding previously and add new one.
        #This might not be the safest thing to do
        print("Adding another trigger event though update was called")
        notifications['LambdaFunctionConfigurations'].append(trigger_config(event_details))
    #upload config back to s3 bucket
    return put_notifications(event_details, notifications)

def delete_resource(event, context):
    event_details = process_event(event, context)
    notifications = get_current_notifications(event_details)
    #look for id==trigger_name in list
    current_trigger_index = find_trigger(event_details, notifications['LambdaFunctionConfigurations'])
    if current_trigger_index:
        #remove trigger in list (which is the same object as in notifications dict)
        notifications['LambdaFunctionConfigurations'].pop(current_trigger_index)
        return put_notifications(event_details, notifications, set_physical_resource_id = False)
    #Trigger not found. Still returning success - something to check
    return (True, dict(Message="Warning: no trigger found to delete"))

def test_resource(event, context):
    return (False, dict())

def handler(event, context):
    print("event")
    print(event)
    print("context")
    print(context)
    lambda_handler(
        event,
        context,
        create_function = create_resource,
        delete_function = delete_resource,
        update_function = update_resource,
        test_function   = test_resource,
    )
