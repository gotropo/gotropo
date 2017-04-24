import boto3

def handler(event, context):
    print("Working on getting event details")
    action    = event["Action"]
    instances = event["Instances"]
    region    = event["Region"]
    ec2 = boto3.client('ec2', region_name=region)
    print("Working on Instances now")
    if(action == "Start" ):
        ec2.start_instances(InstanceIds=instances)
        print 'Starting Instances: ' + str(instances)
    elif( action == "Stop" ):
        ec2.stop_instances(InstanceIds=instances)
        print 'Stoped Instances: ' + str(instances)
    else:
        print 'No Such Action: ' + str(action)
