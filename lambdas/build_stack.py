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
dest          = path.join(deploy_env,environ['destination'])
build_cf_json = path.join(deploy_env,environ['build_cloudformation_json'])

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

def template_url():
    url = "https://s3-{aws_region}.amazonaws.com/".format(aws_region = aws_region)
    url += path.join(deploy_bucket, build_cf_json)
    return url

def handler(event, context):
    if debug:
        print("event:")
        print(event)
        print("Stack URL:")
        print(template_url())

    event_info    = process_event(event)
    cf = boto3.client('cloudformation')
    cf.create_stack(
        StackName=app_name+'-'+stack_type,
        TemplateURL=template_url(),
        OnFailure='DELETE',
        Parameters=[{'ParameterKey': cf_set_param, 'ParameterValue':event_info['source']}]
    )
