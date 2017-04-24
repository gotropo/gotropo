import boto3
from os import environ
from os import path

debug = True

app_name      = environ['app_name']
deploy_bucket = environ['deploy_bucket']
deploy_env    = environ['deploy_env']
stack_type    = environ['stack_type']
aws_region    = environ['aws_region']
cf_set_param  = environ['cf_param']

def process_event(event):
    if len(event['Records']) > 1:
        raise(NotImplementedError,"More than 1 record in event not implemented")
    obj = event['Records'][0]['s3']
    return dict(
        bucket = obj['bucket']['name'],
        source = obj['object']['key'],
    )

def filename(obj_key):
    return path.basename(obj_key)

def handler(event, context):
    if debug:
        print("event:")
        print(event)

    event_info    = process_event(event)
    source_file = path.basename(event_info['source'])
    cf = boto3.client('cloudformation')
    cf.update_stack(
        StackName=app_name+'-'+stack_type,
        UsePreviousTemplate=True,
        Parameters=[{'ParameterKey': cf_set_param, 'ParameterValue': source_file}]
    )
