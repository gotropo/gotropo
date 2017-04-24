import boto3
from os import environ
from os import path

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
    dest       = path.join(environ['deploy_env'],environ['destination'])
    event_info = process_event(event)

    print("event_info")
    print(event_info)
    print("dest")
    print(dest)
    print("key")
    print(path.join(dest, filename(event_info['source'])))

    s3 = boto3.client('s3')
    s3.copy_object(
        Bucket = event_info['bucket'],
        CopySource = dict(Bucket=event_info['bucket'], Key = event_info['source']),
        Key = path.join(dest, filename(event_info['source'])),
    )
