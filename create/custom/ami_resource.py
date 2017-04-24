from lambda_signals.signals import lambda_handler
import boto3
from botocore.exceptions import ClientError
import datetime
import time

debug = True

def process_event(event):
    return dict(
        stack_name    = event['ResourceProperties']['StackName'],
        resource_name = event['LogicalResourceId'],
        autoscale_grp = event['ResourceProperties']['AutoScaleGrp'],
        aws_region    = event['ResourceProperties']['AwsRegion'],
    )

def get_client(region_name):
    return boto3.client("ec2", region_name = region_name)

def get_as_client(region_name):
    return boto3.client("autoscaling", region_name = region_name)

def get_ec2_id(autoscale_group, region_name):
    as_client = get_as_client(region_name)
    as_grp_list = as_client.describe_auto_scaling_groups(AutoScalingGroupNames=[autoscale_group])
    if len(as_grp_list['AutoScalingGroups']) != 1:
        raise Exception("ERROR: multiple autoscaling groups found")
    return as_grp_list['AutoScalingGroups'][0]['Instances'][0]['InstanceId']

def check_ami_exists(client):
    try:
        response = client.describe_images(Filters=[{'Name':'tag:custom:uuid','Values':[uuid]}])
        if response.get('ResponseMetadata').get('HTTPStatusCode') == 200:
            if len(response.get('Images',[])) > 0:
                return (True, response['Images'][0]['ImageId'])
    except:
        return (False, dict())

def create(stack_name, resource_name, autoscale_grp, aws_region):
    client = get_client(aws_region)
    success = False
    datenow = datetime.datetime.now().strftime("%Y_%m_%d_%H%M")
    ec2_label = resource_name + datenow
    ec2_id = get_ec2_id(autoscale_grp, aws_region)
    make_response = client.create_image(InstanceId=ec2_id, Name=ec2_label, NoReboot=False)
    if make_response.get('ResponseMetadata').get('HTTPStatusCode') == 200:
        success = True
        ami_id = make_response.get('ImageId')
        client.create_tags(
            Resources=[ami_id],
            Tags = [{
                "Key":"cloudformation:amimanager:stack-name",
                "Value":stack_name,
            },
            {
                "Key":"cloudformation:amimanager:logical-id",
                "Value":resource_name,
            }
            ],
        )
    if success:
       print("Success")
       time.sleep(60)
       client = boto3.client("autoscaling", region_name = aws_region)
       response = client.update_auto_scaling_group(AutoScalingGroupName=autoscale_grp,
                                                        MinSize=0, DesiredCapacity=0)
       return (True, dict(PhysicalResourceId=ami_id,ImageId=ami_id))
    #TODO: set autoscale group size to 0
    return (False, dict())

def delete(aws_region):
    #TODO: fix delete old AMIs
    return (True, dict())
    #client = get_client(aws_region)

    #(ami_exists, ami_id) = check_ami_exists(client)
    #if ami_exists:
    #    client.deregister_image(ImageId = ami_id)
    #    return (True, dict(DeletedAmiId = ami_id))
    #return (True, dict(Info = "AMI not found"))

def create_resource(event, context):
    if debug:
        print("event")
        print(event)
        print("context")
        print(vars(context))
    event_details = process_event(event)
    return create(**event_details)

def update_resource(event, context):

    event_details = process_event(event)
    return create(**event_details)
    #TODO: delete old ami
    #if old_uuid != event_details['ami_uuid']:
    #    (ami_existed, ami_id) = delete(old_uuid, event_details['aws_region'])
    #    return create(**event_details)
    #else:
    #    return (True, dict(Info="Ami uuid not changed"))

def delete_resource(event, context):
    if debug:
        print("event")
        print(event)
        print("context")
        print(vars(context))
    event_details = process_event(event)

    return delete(event_details['aws_region'])

def test_resource(event, context):
    print("Add tests here")
    return (True, dict())

def handler(event, context):
    lambda_handler(
        event,
        context,
        create_function = create_resource,
        delete_function = delete_resource,
        update_function = update_resource,
        test_function   = test_resource,
    )

if __name__ == "__main__":
    class FakeContext(object):
        def __init__(self):
            context = {
                'aws_request_id': 'a3de505e-f16b-42f4-b3e6-bcd2e4a73903',
                'log_stream_name': '2015/10/26/[$LATEST]c71058d852474b9895a0f221f73402ad',
                'invoked_function_arn': 'arn:aws:lambda:us-west-2:123456789012:function:ExampleCloudFormationStackName-ExampleLambdaFunctionResourceName-AULC3LB8Q02F',
                'client_context': None,
                'log_group_name': '/aws/lambda/ExampleCloudFormationStackName-ExampleLambdaFunctionResourceName-AULC3LB8Q02F',
                'function_name': 'ExampleCloudFormationStackName-ExampleLambdaFunctionResourceName-AULC3LB8Q02F',
                'function_version': '$LATEST',
                'identity': '<__main__.CognitoIdentity object at 0x7fd7042a2b90>',
                'memory_limit_in_mb': '128'
            }
            self.__dict__.update(context)

    event = {
        'StackId': 'Test',
        'RequestId': '123',
        'LogicalResourceId': '123',
        'RequestType':'Test',
        'ResponseURL':'Test',
        'test':'test_value_1'
    }
    context = FakeContext()
    handler(event, context)
