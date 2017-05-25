#!/usr/bin/env python
'''
Send memory usage metrics to Amazon CloudWatch
This is intended to run on an Amazon EC2 instance and requires an IAM
role allowing to write CloudWatch metrics. Alternatively, you can create
a boto credentials file and rely on it instead.
Original idea based on https://github.com/colinbjohnson/aws-missing-tools
(c) 2015 Shahar Evron, all rights reserved;
You are free to use, modify and redistribute this software in any form
under the conditions described in the LICENSE file included.
'''
import sys
import re
import subprocess
from boto.ec2 import cloudwatch
from boto.ec2 import connect_to_region
from boto.utils import get_instance_metadata
def collect_memory_usage():
    meminfo = {}
    pattern = re.compile('([\w\(\)]+):\s*(\d+)(:?\s*(\w+))?')
    with open('/proc/meminfo') as f:
        for line in f:
            match = pattern.match(line)
            if match:
                # For now we don't care about units (match.group(3))
                meminfo[match.group(1)] = float(match.group(2))
    return meminfo
def send_multi_metrics(instance_id, region, metrics, namespace='EC2/Memory',
                        unit='Percent'):
    '''
    Send multiple metrics to CloudWatch
    metrics is expected to be a map of key -> value pairs of metrics
    '''
    cw = cloudwatch.connect_to_region(region)
    cw.put_metric_data(namespace, metrics.keys(), metrics.values(),
                       unit=unit,
                       dimensions={"InstanceId": instance_id})
def yield_lines(data):
    for line in data.split("\n"):
        yield line
def line_to_list(line):
    return re.sub(" +", " ", line).split()
def send_disk_metrics(region, metric, unit, value, dim):
    connection = cloudwatch.connect_to_region(region)
    connection.put_metric_data(
               namespace = 'System/Linux',
               name      = metric,
               unit      = unit,
               value     = value,
               dimensions= dim
            )
def get_disk_metrics(instance_id, region):
    p = subprocess.Popen("df -l -x tmpfs  -x devtmpfs | sed 's/  */ /g'", stdout=subprocess.PIPE, shell=True)
    dfdata, _ = p.communicate()
    dfdata = dfdata.replace("Mounted on", "Mounted_on")
    lines = yield_lines(dfdata)
    headers = line_to_list(lines.next())
    for line in lines:
        if (line == ''):
           continue
        line = line.split(' ')
        percent_used   = line[4][:-1]
        disk_used      = (int(line[2])/(1024*1024))
        disk_available = (int(line[3])/(1024*1024))
        dim={"InstanceId": instance_id, 'MountPath': line[5]};
        print(line[0],percent_used,disk_used , disk_available)
        send_disk_metrics(region, 'DiskSpaceUtilization','Percent', percent_used, dim)
        send_disk_metrics(region, 'DiskSpaceUsed','Gigabytes', disk_used, dim)
        send_disk_metrics(region, 'DiskSpaceAvailable','Gigabytes', disk_available, dim)
def get_asg_name(region,inst_id):

    conn=connect_to_region(region)
    reservations = conn.get_all_instances(instance_ids=[inst_id])
    instances = [i for r in reservations for i in r.instances]
    return(instances[0].tags.get('aws:autoscaling:groupName', None))
def send_asg_metrics(asg_name, region, metrics, namespace="ASG-Custom-Matrix",
                        unit='Percent'):
    cw = cloudwatch.connect_to_region(region)
    cw.put_metric_data(namespace, metrics.keys(), metrics.values(),
                       unit=unit,
                       dimensions={"AutoScalingGroupName": asg_name})

if __name__ == '__main__':
    metadata = get_instance_metadata()
    instance_id = metadata['instance-id']
    region = metadata['placement']['availability-zone'][0:-1]
    asg_name = get_asg_name(region,instance_id)
    mem_usage = collect_memory_usage()
    mem_free = mem_usage['MemAvailable']
    mem_used = mem_usage['MemTotal'] - (mem_free)
    if mem_usage['SwapTotal'] != 0 :
        swap_used = mem_usage['SwapTotal'] - mem_usage['SwapFree'] - mem_usage['SwapCached']
        swap_percent = swap_used / mem_usage['SwapTotal'] * 100
    else:
        swap_percent = 0
    metrics = {'MemUsage': mem_used / mem_usage['MemTotal'] * 100,
               'SwapUsage': swap_percent }
    send_multi_metrics(instance_id, region, metrics)
    get_disk_metrics(instance_id, region)
    if asg_name: send_asg_metrics(asg_name,region,metrics)
