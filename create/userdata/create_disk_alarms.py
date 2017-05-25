from boto.ec2 import cloudwatch
from boto.utils import get_instance_metadata
from boto.ec2 import connect_to_region
import argparse

def get_inst_name(region,inst_id):
    conn=connect_to_region(region)
    reservations = conn.get_all_instances(instance_ids=[inst_id])
    instances = [i for r in reservations for i in r.instances]
    return(instances[0].tags.get('Name',None))

def getMetric(instance_id, metric_Name):
    return cw.list_metrics(
        dimensions=
        {
            'InstanceId': instance_id
        },
        metric_name=metric_Name
    )

def createAlarm(
        name,
        comparison,
        threshold,
        period,
        eval_periods,
        statistic,
        alarm_action,
        ok_actions):

    metric.create_alarm(
        name=name,
        comparison=comparison,
        threshold=threshold,
        period=period,
        evaluation_periods=eval_periods,
        statistic=statistic,
        alarm_actions=alarm_action,
        ok_actions=ok_actions
    )

if __name__ == '__main__':
    metadata = get_instance_metadata()
    metric_Name='DiskSpaceUsed'
    instance_id = metadata['instance-id']
    region = metadata['placement']['availability-zone'][0:-1]
    cw = cloudwatch.connect_to_region(region)
    metric = getMetric(instance_id,metric_Name)[0]
    high_disk_threshold=70
    period=60
    evaluation_periods=7
    alarm_actions=[]
    alarm_name='{}-{}-{}'.format("HighDiskUsageAlarm",get_inst_name(region,instance_id),instance_id)

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true", required=False)
    group.add_argument("--remove", action="store_true", required=False)
    group.add_argument("--status", action="store_true", required=False)
    args = parser.parse_args()
    
    if args.create: createAlarm(alarm_name,'>=',high_disk_threshold,period,evaluation_periods,'Average',alarm_actions,None)
    elif args.remove: cw.delete_alarms([alarm_name])
    elif args.status: print("TO DO: Get Alarm Status from CloudWatch")
