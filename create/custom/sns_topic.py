from lambda_signals.signals import lambda_handler
import boto3

debug = True

def get_sns(region_name = "us-east-1"):
    return boto3.client("sns", region_name = region_name)

def create_subscription(sns, topic_arn, contact):
    subscription = sns.subscribe(
        TopicArn = topic_arn,
        Protocol = "SMS",
        Endpoint = contact,
    )
    return subscription['ResponseMetadata']['HTTPStatusCode'] == 200

def check_topic_exists(sns, topic_name, next_token = None):
    if next_token:
        topics = sns.list_topics(NextToken=next_token)
    else:
        topics = sns.list_topics()
    topic_arn = [t['TopicArn'] for t in topics['Topics'] if t['TopicArn'].split(':')[5] == topic_name]
    if len(topic_arn) == 1:
        return (True, topic_arn[0])
    elif len(topic_arn) > 1:
        raise(Exception("Multiple Topics found"))
    elif topics.get('NextToken'):
        return check_topic_exists(sns, topic_name, topics.get('NextToken'))
    return (False, "")

def all_subscriptions(sns, topic_arn, next_token = None):
    if next_token:
        subs = sns.list_subscriptions(NextToken=next_token)
    else:
        subs = sns.list_subscriptions()
    subscriptions = (s['SubscriptionArn'] for s in subs['Subscriptions'] if s['TopicArn'] == topic_arn)
    for s in subscriptions:
        yield s
    if subs.get('NextToken'):
        for s in all_subscriptions(sns, topic_arn, subs.get('NextToken')):
            yield s

def create(sns_topic_name, contacts):
    sns = get_sns()

    (topic_exists, topic_arn) = check_topic_exists(sns, sns_topic_name)

    if topic_exists:
        return (False, dict(Error = " ".join(["Topic ", sns_topic_name,"exists"])))

    request_topic = sns.create_topic(Name = sns_topic_name)
    if request_topic['ResponseMetadata']['HTTPStatusCode'] == 200:
        topic_arn = request_topic['TopicArn']
        for c in contacts:
            if not create_subscription(sns, topic_arn, c):
                print("".join(["Error creating subscription for ",c]))
                delete(sns_topic_name) #TODO: check this works as well
                return (False, dict())
        return (True, dict(TopicArn = topic_arn))
    return (False, dict())

def delete(sns_topic_name):
    sns = get_sns()

    (topic_exists, topic_arn) = check_topic_exists(sns, sns_topic_name)
    if topic_exists:
        for s in all_subscriptions(sns, topic_arn):
            sns.unsubscribe(SubscriptionArn=s)
            #TODO: test unsubscribe completes
        sns.delete_topic(TopicArn=topic_arn)
        return (True, dict(DeletedTopicArn = topic_arn))
    return (True, dict(Info = "Topic not found"))

def create_sns_topic(event, context):
    if debug:
        print("event")
        print(event)
        print("context")
        print(vars(context))
    topic_name = event['ResourceProperties']['SnsTopicName']
    contacts = event['ResourceProperties']['Contacts']
    return create(topic_name, contacts)

def update_sns_topic(event, context):
    old_topic = event['OldResourceProperties']['SnsTopicName']
    topic_name = event['ResourceProperties']['SnsTopicName']
    contacts = event['ResourceProperties']['Contacts']
    (topic_existed, topic_arn) = delete(old_topic)
    if (topic_existed):
        return create(topic_name, contacts)
    return (False, dict(Error = " ".join(["Topic ", old_topic, "does not exist"])))

def delete_sns_topic(event, context):
    if debug:
        print("event")
        print(event)
        print("context")
        print(vars(context))

    topic_name = event['ResourceProperties']['SnsTopicName']
    return delete(topic_name)

def test_sns_topic(event, context):
    print("Add tests here")
    return (True, dict())

def handler(event, context):
    lambda_handler(
        event,
        context,
        create_function = create_sns_topic,
        delete_function = delete_sns_topic,
        update_function = update_sns_topic,
        test_function   = test_sns_topic,
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
