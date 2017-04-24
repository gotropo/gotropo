from lambda_signals.signals import lambda_handler
import boto3

debug = True

def get_client(region_name = "us-east-1"):
    return boto3.client("cloudwatch", region_name = region_name)

def create_alarm(client,
        alarm_name,
        health_check_id,
        topic_arn,
        threshold = 1,
        comparison_operator = "LessThanThreshold",
        metric_name = "HealthCheckStatus",
        statistic = "Minimum",
        period = 60,
        namespace = "AWS/Route53",
        evaluation_periods = 1):
    alarm = client.put_metric_alarm(
        AlarmName = alarm_name,
        AlarmDescription = "Alarm for "+alarm_name,
        AlarmActions = [ topic_arn ],
        OKActions    = [ topic_arn ],
        Namespace = namespace,
        MetricName = metric_name,
        Statistic = statistic,
        Dimensions = [dict(Name="HealthCheckId",Value=health_check_id)],
        Period = period,
        Threshold = 1,
        EvaluationPeriods = evaluation_periods,
        ComparisonOperator = comparison_operator,
    )
    return (alarm['ResponseMetadata']['HTTPStatusCode'] == 200, alarm)

def check_alarm_exists(client, alarm_name, next_token = None):
    alarm = client.describe_alarms(AlarmNames = [alarm_name])
    if len(alarm['MetricAlarms']) == 1:
        return (True, alarm['MetricAlarms'][0])
    elif len(alarm['MetricAlarms']) > 1:
        raise(Exception("Multiple Alarms found"))
    return (False, "")

def create(alarm_name, health_check_id, topic_arn):
    client = get_client()

    (alarm_exists, alarm) = check_alarm_exists(client, alarm_name)

    if alarm_exists:
        return (False, dict(Error = " ".join(["Alarm ", alarm_name, "exists"])))

    (success, alarm) = create_alarm(
        client,
        alarm_name,
        health_check_id,
        topic_arn
    )
    if success:
        return (True, dict(AlarmName=alarm_name)) #TODO: return more info
    return (False, dict())

def delete(alarm_name):
    client = get_client()

    (alarm_exists, alarm) = check_alarm_exists(client, alarm_name)
    if alarm_exists:
        client.delete_alarms(AlarmNames=[alarm_name])
        return (True, dict(DeletedAlarm = alarm_name))
    return (True, dict(Info = "Alarm not found"))

def create_resource(event, context):
    if debug:
        print("event")
        print(event)
        print("context")
        print(vars(context))
    alarm_name      = event['ResourceProperties']['AlarmName']
    health_check_id = event['ResourceProperties']['HealthCheckId']
    topic_arn       = event['ResourceProperties']['TopicArn']
    return create(alarm_name, health_check_id, topic_arn)

def update_resource(event, context):
    old_alarm = event['OldResourceProperties']['AlarmName']
    alarm_name = event['ResourceProperties']['AlarmName']
    health_check_id = event['ResourceProperties']['HealthCheckId']
    topic_arn       = event['ResourceProperties']['TopicArn']
    (alarm_existed, alarm) = delete(old_alarm)
    if (alarm_existed):
        return create(alarm_name, health_check_id, topic_arn)
    return (False, dict(Error = " ".join(["Alarm ", old_alarm, "does not exist"])))

def delete_resource(event, context):
    if debug:
        print("event")
        print(event)
        print("context")
        print(vars(context))

    alarm_name = event['ResourceProperties']['AlarmName']
    return delete(alarm_name)

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
