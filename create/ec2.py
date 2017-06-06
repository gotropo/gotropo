import boto3
from troposphere import elasticloadbalancing
from troposphere import policies
from troposphere import autoscaling
from troposphere import cloudwatch
from troposphere import Tags
from troposphere.autoscaling import Tags as ASTags
from troposphere.autoscaling import ScheduledAction
from troposphere.cloudwatch import MetricDimension
from troposphere.autoscaling import NotificationConfigurations
from troposphere import FindInMap
from troposphere import Join, Sub
from troposphere import GetAtt
from troposphere import Base64
from troposphere import Ref
from troposphere import ec2
from troposphere import cloudformation
from collections import OrderedDict
import os
from .utils import update_dict
import yaml
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def keyappend(ob, key, value):
    v = ob.get(key)
    if v:
        v.append(value)
    else:
        ob[key] = [value]

def add_cloudconf(msg, name, clcfg):
    cfg = yaml.dump(clcfg, default_flow_style=False)
    message_part = MIMEText(cfg,"cloud-config",'us-ascii')
    message_part.add_header('Content-Disposition','attachment; filename='+name)
    msg.attach(message_part)

def find_cloudfront_sec_group(region):
    ec2 = boto3.client("ec2", region_name = region)

    r = ec2.describe_security_groups(Filters=[{'Name':'tag:Name','Values':['cloudfront']}])
    if r['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise(RuntimeError("Error retrieving cloudfront security group"))
    elif len(r['SecurityGroups']) > 1:
        raise(RuntimeError("Multiple cloudfront security groups found"))
    else:
        return r['SecurityGroups'][0]['GroupId']

def elb(template, elb_name, billing_id, elb_subnet, sec_grp, ssl_cert, health_chk_port, port_map, ops):
    aws_region = ops.aws_region

    sec_grp_list=[]
    if(ops.get("elb_cloudfront_only") == True):
        cloudfront_sg = find_cloudfront_sec_group(aws_region)
        sec_grp_list = [sec_grp, cloudfront_sg]
    else:
        sec_grp_list = [sec_grp]
    elb_bucket_prefix= ops.app_name
    default_healthcheck_settings = dict(
        Target             = "TCP:"+health_chk_port, #TODO: allow multiple app ports
        HealthyThreshold   = "2",
        UnhealthyThreshold = "2",
        Interval           = "5",
        Timeout            = "4",
    )
    healthcheck_settings= ops.get("healthcheck_settings") or default_healthcheck_settings
    elastic_elb = template.add_resource(elasticloadbalancing.LoadBalancer(
        elb_name,
        Tags = Tags(BillingID = billing_id),
        LoadBalancerName = elb_name,
        Subnets          = elb_subnet,
        HealthCheck      = elasticloadbalancing.HealthCheck(**healthcheck_settings),
        AccessLoggingPolicy    = elasticloadbalancing.AccessLoggingPolicy( Enabled = True,
                                                S3BucketName    = ops.elb_bucket,
                                                S3BucketPrefix  = elb_bucket_prefix,
                                            ),
        # Enable ConnectionDrainingPolicy
        ConnectionDrainingPolicy = elasticloadbalancing.ConnectionDrainingPolicy(
            Enabled = True,
            Timeout = "300"
            ),
        Listeners = [elb_listener(port = value[0], instance_port = value[1], ssl_cert = ssl_cert, proto=proto) for proto, value in port_map.items()],
        CrossZone = True,
        SecurityGroups = sec_grp_list,
        Scheme         = "internet-facing",
    ))
    return Ref(elastic_elb)

def elb_listener(port, instance_port, ssl_cert, proto="HTTPS", instance_proto="HTTP"):
    """Create ELB listener
    TODO: Allow HTTP connections without having to provide an SSLCert
    """
    if proto.lower() == "https":
        return elasticloadbalancing.Listener(
           LoadBalancerPort = port,
           InstancePort     = instance_port,
           Protocol         = proto,
           InstanceProtocol = instance_proto,
           SSLCertificateId = ssl_cert,
           )
    return elasticloadbalancing.Listener(
        LoadBalancerPort=port,
        InstancePort=instance_port,
        Protocol=proto,
        InstanceProtocol=instance_proto
        )

def launch_config(template, name, key_name, userdata, sec_grp, iam_profile, root_volume_size, image = None):

    if not image:
        image = FindInMap("RegionMap", Ref("AWS::Region"), "AMI")

    lc_ops = dict(
            ImageId            = image,
            SecurityGroups     = [sec_grp],
            InstanceType       = Ref("InstanceType"),
            UserData           = userdata,
            IamInstanceProfile = iam_profile,
    )

    #TODO: clean up
    if key_name:
        lc_ops.update(
            KeyName            = key_name,
        )
    if root_volume_size:
       lc_ops.update(
            BlockDeviceMappings= [ ec2.BlockDeviceMapping(
                                       DeviceName="/dev/xvda",
                                       Ebs=ec2.EBSBlockDevice( VolumeSize=root_volume_size )
                                     ),
                                 ],
        )
    return template.add_resource(autoscaling.LaunchConfiguration(
        name,
        **lc_ops
    ))

def update_policy():
    return policies.UpdatePolicy(
            AutoScalingReplacingUpdate = policies.AutoScalingReplacingUpdate(
                WillReplace=True,
            ),
            AutoScalingRollingUpdate = policies.AutoScalingRollingUpdate(
                PauseTime             = 'PT20M',
                MinInstancesInService = Ref("MinScaleCapacity"),
                MaxBatchSize          = '1',
                WaitOnResourceSignals = True #TODO: test using this
            )
        )

def creation_policy():
    return policies.CreationPolicy(
            AutoScalingCreationPolicy = policies.AutoScalingCreationPolicy(
                MinSuccessfulInstancesPercent = 100,
            ),
            ResourceSignal = policies.ResourceSignal(Timeout = "PT50M")
        )

def userdata_exports(ops, app_cfn_options):
    cf_param_refs = {k:v for k,v in app_cfn_options.cf_params.items()}
    userdata_vars = {k:ops.get(v) for k,v in ops.userdata_exports.items()}
    userdata_vars.update(ops.get("userdata_values"))
    userdata_vars.update(app_cfn_options.userdata_objects)
    return userdata_vars

def app_userdata(ops, app_cfn_options, resource_name):
    log_group        = app_cfn_options.log_group
    autoscale_name   = app_cfn_options.autoscale_name
    userdata_file    = ops.userdata_file
    install_packages = ops.install_packages

    userdata_vars = userdata_exports(ops, app_cfn_options)

    if ops.get("userdata_values"):
        userdata_vars.update(ops.userdata_values)
    if ops.get("app_prerun"):
        app_prerun_mappings = [(prerun_name,prerun_setup["var_export"]) for prerun_name,prerun_setup in ops.app_prerun.items()]
        for prerun_name, var_export in app_prerun_mappings:
            mapping_name = prerun_name.replace("_","-")
            update_dict(userdata_vars, {var_export:FindInMap("PrerunValues", mapping_name, "ReturnString")})
    if ops.get("cf_params"):
        param_exports = ops.get("cf_params")
        for param_name, param_details in sorted(param_exports.items()):
            param_options = param_details.get("options")
            #TODO: clean this up >
            if param_options:
                if not param_options.get("NoUserdataExport"):
                    if userdata_vars.get(param_name):
                        raise(ValueError("Multiple userdata vars with same key"))
                userdata_vars[param_name] = app_cfn_options.cf_params[param_name]
            else:
                if userdata_vars.get(param_name):
                    raise(ValueError("Multiple userdata vars with same key"))
                userdata_vars[param_name] = app_cfn_options.cf_params[param_name]
            #TODO: clean at least to here <
    userdata_vars.update(dict(
        LOG_GROUP = log_group,
        resource_name  = resource_name,
    ))


    userdata = multipart_userdata(
            bash_files       = [userdata_file],
            install_packages = install_packages,
            cfn_signal       = autoscale_name,
            sub_values       = userdata_vars,
            enable_cre_disk_alarm = ops.get("enable_disk_alarm", False),
    )
    return userdata

def app_autoscale(template, ops, app_cfn_options, ami_image = None):
    name                    = app_cfn_options.autoscale_name
    billing_id              = ops.billing_id
    lc_name                 = app_cfn_options.launch_config_name
    app_name                = ops.app_name
    deploy_bucket           = ops.deploy_bucket
    deploy_env              = ops.deploy_env
    default_ami             = ops.ami_image
    root_volume_size        = ops.get('root_volume_size')
    elb_name                = app_cfn_options.elb_name
    elb                     = app_cfn_options.elb
    key_name                = app_cfn_options.cf_params.get('KeyName')
    app_subnets             = app_cfn_options.app_subnets
    app_sg                  = app_cfn_options.app_sg
    iam_profile             = app_cfn_options.iam_profile
    autoscale_name          = app_cfn_options.autoscale_name
    high_cpu_thres          = "40"
    low_cpu_thres           = "10"
    mongo_dbs               = ops.get("mongo_dbs")
    rabbitmq_server         = ops.get("rabbitmq_server")
    autoscale_grace_period  = ops.get("autoscale_grace_period")
    asg_topic_arn           = ops.get("asg_topic_arn")

    if ami_image is None:
        ami_image = default_ami
        ec2_userdata = app_userdata(ops, app_cfn_options, autoscale_name)
    else:
        #TODO: error if ami image and userdata are defined.
        #Ami should be setup without requiring userdata
        ec2_userdata = ""

    as_grp = autoscale(
        template,
        name,
        lc_name     = lc_name,
        env         = deploy_env,
        app_name    = app_name,
        root_volume_size = root_volume_size,
        key_name    = key_name,
        sec_grp     = app_sg,
        iam_profile = iam_profile,
        billing_id  = billing_id,
        subnets     = app_subnets,
        userdata    = ec2_userdata,
        elbs        = elb,
        image       = ami_image,
        grace_period = autoscale_grace_period,
        asg_topic_arn= asg_topic_arn
    )

    up_scale = scaling_policy(
        template,
        "".join([name,"ScaleUp"]),
        autoscale_grp = Ref(as_grp),
        scaling_adjustment = 4,
    )
    down_scale = scaling_policy(
        template,
        "".join([name,"ScaleDown"]),
        autoscale_grp = Ref(as_grp),
        scaling_adjustment = -2,
    )

    high_cpu(
        template,
        "".join([name,"HighCpuAlarm"]),
        alarm_description = "Alarm for "+name+" appservers high CPU scale up",
        autoscale_grp = Ref(as_grp),
        scaling_policy = Ref(up_scale),
        threshold = high_cpu_thres
    )

    low_cpu(
        template,
        "".join([name,"NotLowCpuAlarm"]),
        alarm_description = "Alarm for "+name+" appservers low CPU scale down",
        autoscale_grp = Ref(as_grp),
        scaling_policy = Ref(down_scale),
        threshold = low_cpu_thres,
    )

    if ops.get("asg_mem_alarm"):
        template.add_resource(cloudwatch.Alarm(
            '{}{}'.format("HighMemUsageAlarm",name),
            AlarmName='{}{}'.format("HighMemUsageAlarm",name),
            AlarmDescription='{}{}'.format("High Memory Usage for ASG",name),
            Dimensions=[MetricDimension(
                Name="AutoScalingGroupName",
                Value=Ref(as_grp),
            )],
            Threshold=str(ops.asg_mem_alarm['threshold_high']),
            ComparisonOperator=ops.asg_mem_alarm['comp_oper_high'],
            MetricName="MemUsage",
            Statistic=ops.asg_mem_alarm['statistic_high'],
            Period=ops.asg_mem_alarm['period_high'],
            Namespace="ASG-Custom-Matrix",
            EvaluationPeriods=ops.asg_mem_alarm['eval_period_high'],
            AlarmActions=[ops.sns_topic_arn],
            ActionsEnabled=True
        ))
        template.add_resource(cloudwatch.Alarm(
            '{}{}'.format("LowMemUsageAlarm", name),
            AlarmName='{}{}'.format("LowMemUsageAlarm", name),
            AlarmDescription='{}{}'.format("Low Memory Usage for ASG", name),
            Dimensions=[MetricDimension(
                Name="AutoScalingGroupName",
                Value=Ref(as_grp),
            )],
            Threshold=str(ops.asg_mem_alarm['threshold_low']),
            ComparisonOperator=ops.asg_mem_alarm['comp_oper_low'],
            MetricName="MemUsage",
            Statistic=ops.asg_mem_alarm['statistic_low'],
            Period=ops.asg_mem_alarm['period_low'],
            Namespace="ASG-Custom-Matrix",
            EvaluationPeriods=ops.asg_mem_alarm['eval_period_low'],
            AlarmActions=[ops.sns_topic_arn],
            ActionsEnabled=True
        ))

    if (ops.get("use_shut_scheduled_action")):
            schedule_action_shut(template, name, ops, autoscale_grp = Ref(as_grp))

    if (ops.get("use_start_scheduled_action")):
            schedule_action_start(template, name, ops, autoscale_grp = Ref(as_grp))

    return as_grp

def scaling_policy(template, name, autoscale_grp, scaling_adjustment,
        adjustment_type = "ChangeInCapacity", cooldown = 180, ):

    return template.add_resource(autoscaling.ScalingPolicy(
        name,
        AutoScalingGroupName = autoscale_grp,
        Cooldown = cooldown,
        AdjustmentType = adjustment_type,
        PolicyType = "SimpleScaling",
        ScalingAdjustment = scaling_adjustment,
    ))

def cpu_alarm(template, name, alarm_description, autoscale_grp, scaling_policy, threshold, comparison_operator,
        statistic = "Average", period = 60, eval_periods = 2, namespace = "AWS/EC2", use_ok_action = False):

    if use_ok_action:
        ok_actions = [scaling_policy]
        alarm_actions = []
    else:
        ok_actions = []
        alarm_actions = [scaling_policy]

    return template.add_resource(cloudwatch.Alarm(
        name,
        AlarmName = name,
        AlarmDescription = alarm_description,
        Dimensions = [MetricDimension(
            Name = "AutoScalingGroupName",
            Value = autoscale_grp,
        )],
        AlarmActions = alarm_actions,
        OKActions = ok_actions,
        Threshold = threshold,
        ComparisonOperator = comparison_operator,
        MetricName = "CPUUtilization",
        Statistic = statistic,
        Period = period,
        Namespace = namespace,
        EvaluationPeriods = eval_periods,
    ))

def high_cpu(template, name, alarm_description, autoscale_grp, scaling_policy, threshold):
    #TODO: move this to generic cloudwatch alarm function
    return cpu_alarm(
        template,
        name = name,
        alarm_description = alarm_description,
        autoscale_grp = autoscale_grp,
        scaling_policy = scaling_policy,
        threshold = threshold,
        comparison_operator = "GreaterThanThreshold",
    )

def low_cpu(template, name, alarm_description, autoscale_grp, scaling_policy, threshold):
    #TODO: move this to generic cloudwatch alarm function
    return cpu_alarm(
        template,
        name = name,
        alarm_description = alarm_description,
        autoscale_grp = autoscale_grp,
        scaling_policy = scaling_policy,
        threshold = threshold,
        comparison_operator = "GreaterThanThreshold",
        use_ok_action = True,
    )

def schedule_action_shut(template, name,ops, autoscale_grp):
    name = "".join([name,"ScheduledActionSHUT"])
    desired_capacity = ops.shut_desired_capacity
    min_size         = ops.shut_min_size
    shut_recurrence       = ops.shut_recurrence
    return template.add_resource(autoscaling.ScheduledAction(
                                    name,
                                    AutoScalingGroupName =  autoscale_grp,
                                    DesiredCapacity      =  desired_capacity,
                                    MinSize              =  min_size,
                                    Recurrence           =  shut_recurrence
                                    )
                                )


def schedule_action_start(template, name,ops, autoscale_grp):
    name = "".join([name,"ScheduledActionSTART"])
    desired_capacity = ops.start_desired_capacity
    min_size         = ops.start_min_size
    start_recurrence       = ops.start_recurrence
    return template.add_resource(autoscaling.ScheduledAction(
                                    name,
                                    AutoScalingGroupName =  autoscale_grp,
                                    DesiredCapacity      =  desired_capacity,
                                    MinSize              =  min_size,
                                    Recurrence           =  start_recurrence
                                    )
                                )


def autoscale(template, name, env, lc_name, key_name, sec_grp, iam_profile, app_name, billing_id, subnets,
        root_volume_size = None, userdata = "", elbs = [], image = None, as_grp_tags = {},
        set_min_size = None, set_max_size = None, grace_period = None, asg_topic_arn = None):
    launch_config_1     = launch_config(template,
            name        = lc_name,
            key_name    = key_name,
            image       = image,
            userdata    = userdata,
            sec_grp     = sec_grp,
            iam_profile = iam_profile,
            root_volume_size = root_volume_size
    )

    if not set_min_size:
        min_size = Ref("MinScaleCapacity")
    else:
        min_size = set_min_size
    if not set_max_size:
        max_size = Ref("MaxScaleCapacity")
    else:
        max_size = set_max_size
    astags = (ASTags(Name=(app_name, True))
        + ASTags(BillingID=(billing_id, True))
        + ASTags(Env=(env,True)))
    for t,v in sorted(as_grp_tags.items()):
        astags += ASTags(**{t:(v,True)})

    asg_dict = dict(
           Tags = astags,
           LaunchConfigurationName = Ref(launch_config_1),
           MinSize                 = min_size,
           DesiredCapacity         = min_size,
           MaxSize                 = max_size,
           VPCZoneIdentifier       = subnets,
           UpdatePolicy            = update_policy(),
           CreationPolicy          = creation_policy(),
           HealthCheckGracePeriod  = grace_period or "600",
           MetricsCollection       = [autoscaling.MetricsCollection(
                                     Granularity = "1Minute",
                                     Metrics =  ['GroupMaxSize',
                                     'GroupDesiredCapacity',
                                     'GroupInServiceInstances',
                                     'GroupPendingInstances',
                                     'GroupTerminatingInstances',
                                     'GroupStandbyInstances']
                                     )]
    )
    if elbs:
        elbs = [elbs]
        asg_dict.update(
            LoadBalancerNames          = elbs,
            HealthCheckType            = "ELB",
        )
        if asg_topic_arn:
          asg_dict.update(
            NotificationConfigurations = [ NotificationConfigurations(
                                             NotificationTypes = ["autoscaling:EC2_INSTANCE_LAUNCH_ERROR",
                                                                  "autoscaling:EC2_INSTANCE_TERMINATE_ERROR"],
                                             TopicARN = asg_topic_arn ) ],
       )
    else:
        asg_dict.update( HealthCheckType = "EC2", )

    return template.add_resource(autoscaling.AutoScalingGroup(name, **asg_dict))

def read_file(f):
    contents = []
    try:
        with open(f, 'r') as fh:
            for line in fh:
                if line.strip('\n\r ') == '':
                    continue

                contents.append(line)
    except IOError:
        raise IOError('Error opening or reading file: {}'.format(f))
    return contents

def windows_cloudinit(
        powershell_files = None,
        sub_values = None):
    #TODO: move this. Potentially make multipart userdata Class. From here -->
    class folded_unicode(str): pass
    class literal_unicode(str): pass

    def folded_unicode_representer(dumper, data):
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', data, style='>')
    def literal_unicode_representer(dumper, data):
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', data, style='|')
    reserved_sub_values = ['cfn_signal']

    if sub_values:
        for i in reserved_sub_values:
            if sub_values.get(i):
                raise("Reserved substitution value used in userdata:" + i)
        svals = sub_values.copy()
    else:
        svals = {}
    #--> to here

    def get_cmds(powershell_files):
        for f in powershell_files:
            with open(f, 'r') as fh:
                for line in fh:
                    if line.strip('\n\r ') == '':
                        continue
                    if line[0] == "#":
                        continue
                    yield line.strip('\n\r')


    metadata = cloudformation.Metadata(
        cloudformation.Init(
            cloudformation.InitConfigSets(config1=["initconfig1"]),
            initconfig1=cloudformation.InitConfig(
                commands = { count:dict(command=Sub(cmd, **svals)) for count,cmd in enumerate(get_cmds(powershell_files)) }
            )
        )
    )
    return metadata

def windows_userdata(
        powershell_files = None,
        sub_values = None):
    #TODO: move this. Potentially make multipart userdata Class. From here -->
    class folded_unicode(str): pass
    class literal_unicode(str): pass

    def folded_unicode_representer(dumper, data):
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', data, style='>')
    def literal_unicode_representer(dumper, data):
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', data, style='|')
    reserved_sub_values = ['cfn_signal']

    if sub_values:
        for i in reserved_sub_values:
            if sub_values.get(i):
                raise("Reserved substitution value used in userdata:" + i)
        svals = sub_values.copy()
    else:
        svals = {}
    #--> to here

    yaml.add_representer(folded_unicode, folded_unicode_representer)
    yaml.add_representer(literal_unicode, literal_unicode_representer)

    messages = MIMEMultipart()
    cloudconf = dict()
    put_file = ["<powershell>\n"]
    for b in powershell_files:
        put_file.extend(read_file(b))
    put_file.append("\n</powershell>")
    cloudconf["script"] = literal_unicode("".join(put_file))
    if len(cloudconf) > 0:
        add_cloudconf(messages, "cloudconf.txt", cloudconf)
    cloudconf_userdata = "".join(["#cloud-config","\n",str(yaml.dump(cloudconf))])
    return Base64(Sub(cloudconf_userdata, **svals))


def multipart_userdata(
        bash_files = None,
        install_packages = None,
        cfn_signal = None,
        sub_values = None,
        awslogs = True,
        add_trap_file = True,
        ip_list = None,
        enable_mem_metrics = True,
        enable_cre_disk_alarm = False,
        env_vars = None):

    #TODO: move this. Potentially make multipart userdata Class. From here -->
    import yaml
    class folded_unicode(str): pass
    class literal_unicode(str): pass

    def folded_unicode_representer(dumper, data):
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', data, style='>')
    def literal_unicode_representer(dumper, data):
        return dumper.represent_scalar(u'tag:yaml.org,2002:str', data, style='|')

    yaml.add_representer(folded_unicode, folded_unicode_representer)
    yaml.add_representer(literal_unicode, literal_unicode_representer)
    def trap_signals_file():
        return dict(
            content = literal_unicode("".join(
            [
                "#Source this /trap.sh in userdata script to call cloudformation signals on exit and err\n"
                "signal_code() {\n",
                    "signal=$1\n",
                    "#Signal success to cloudformation which can update autoscaling groups\n",
                    "#TODO: Check the state of cloudformation stack and only signal if needed\n",
                    "set +e\n"
                    "/opt/aws/bin/cfn-signal -e ${!signal} --stack ${AWS::StackName} --resource \"${resource_name}\" --region ${AWS::Region}\n",
                    "set -e\n"
                    "echo Signal Sent\n"
                "}\n",
                "trap 'signal_code $CODE' EXIT\n",
                "trap 'signal_code $CODE' ERR\n",
                "CODE=1\n"
            ])),
            path = "/trap.sh",
            permissions = '0400'
        )
    def wait_signals_file():
        return dict(
            content = literal_unicode("".join(
            [
                "#Source this /wait.sh in userdata script to call cloudformation wait signals on exit and err\n"
                "signal_code() {\n",
                    "signal=$1\n",
                    "#Signal success to cloudformation which can update autoscaling groups\n",
                    "#TODO: Check the state of cloudformation stack and only signal if needed\n",
                    "/opt/aws/bin/cfn-signal -e ${!signal} \"${resource_name}\" || echo \"Ignoring signal error\"\n",
                "}\n",
                "trap 'signal_code $CODE' EXIT\n",
                "trap 'signal_code $CODE' ERR\n",
                "CODE=1\n"
            ])),
            path = "/wait.sh",
            permissions = '0400'
        )

    def env_file(env_values):
        return dict(
            content = literal_unicode("".join(
            [
                "".join(["export ", k, "=\"", str(v), "\"\n"]) for k,v in env_values.items()
            ])),
            path = "/envs.sh",
            permissions = '0400'
        )
    #TODO: --> move

    reserved_sub_values = ['cfn_signal']

    if sub_values:
        for i in reserved_sub_values:
            if sub_values.get(i):
                raise("Reserved substitution value used in userdata:" + i)
        svals = sub_values.copy()
    else:
        svals = {}


    messages = MIMEMultipart()
    cloudconf = dict()
    put_files = []

    if install_packages:
        cloudconf.update(dict(packages=install_packages))
    if ip_list:
        for key,value in sorted(ip_list.items()):
             keyappend(cloudconf,"runcmd","echo "+key+"= "+"".join(["${",key,"}"])+">>/ips.txt")

    if awslogs:
        #TODO: move this out
        keyappend(cloudconf,"packages","awslogs")
        put_files.append(dict(
            content = literal_unicode("".join(
                ["[plugins]\n",
                "cwlogs = cwlogs\n",
                "[default]\n",
                "region = ${AWS::Region}"
                ])),
            path = "/etc/awslogs/awscli.conf.disabled",
            permissions = '0440'
        ))
        put_files.append(dict(
            content= literal_unicode("".join([
                "[general]\n",
                "state_file = /var/awslogs/state/agent-state\n",
                "[/var/log/cloud-init-output]\n",
                "file = /var/log/cloud-init-output.log\n",
                "log_group_name = ${LOG_GROUP}\n",
                "log_stream_name = [INSTANCEID]/cloud-init-output.log\n",
                "datetime_format = %b %d %H:%M:%S"
            ])),
            path = "/etc/awslogs/awslogs.conf.disabled",
            permissions = '0440'
        ))
        keyappend(cloudconf,"runcmd","mv /etc/awslogs/awslogs.conf.disabled /etc/awslogs/awslogs.conf")
        keyappend(cloudconf,"runcmd","mv /etc/awslogs/awscli.conf.disabled /etc/awslogs/awscli.conf")
        keyappend(cloudconf,"runcmd","".join(
            ["sed -i \"s/\[INSTANCEID\]/",
            "$(curl http://169.254.169.254/latest/meta-data/instance-id)/g\"",
            " /etc/awslogs/awslogs.conf"]))
        keyappend(cloudconf,"runcmd","mkdir -p /var/awslogs/state/")
        keyappend(cloudconf,"runcmd","service awslogs restart")

    if cfn_signal:
        cfn_file = dict(content = literal_unicode("".join(
                ["#!/bin/bash -exu\n",
                "/opt/aws/bin/cfn-signal -e 0",
                " --region=${AWS::Region}",
                " --stack=${AWS::StackName}",
                " --resource=${cfn_signal}"
            ])),
            path = "/etc/rc.local", #TODO: fix this, it should be /var/lib/cloud/scripts/per-boot/
            permissions = '0500'
        )
        put_files.append(cfn_file)
        svals['cfn_signal'] = cfn_signal

    if enable_mem_metrics:
        put_files.append(dict(
            content= literal_unicode("".join(read_file(os.path.dirname(os.path.abspath(__file__))+"/userdata/send_mem_metrics.py"))),
            path = '/send_mem_metrics.py',
            permissions = '0555'
        ))
        keyappend(cloudconf,"runcmd", 'echo "*/5 * * * * nobody /send_mem_metrics.py" | sudo tee /etc/cron.d/send_mem_metrics;python /send_mem_metrics.py;sleep 30')

    if enable_cre_disk_alarm:
        put_files.append(dict(
            content= literal_unicode("".join(read_file(os.path.dirname(os.path.abspath(__file__))+"/userdata/create_disk_alarms.py"))),
            path = '/create_disk_alarms.py',
            permissions = '0555'
        ))
        keyappend(cloudconf,"runcmd", 'sed -i "s/^\s*alarm_actions=\[.*$/\ \ \ \ alarm_actions=[\\"${SNS_TOPIC_ARN}\\"]/" /create_disk_alarms.py')

        put_files.append(dict(
            content=literal_unicode("".join(read_file(os.path.dirname(os.path.abspath(__file__)) + "/userdata/cw-alarm"))),
            path='/etc/init.d/cw-alarm',
            permissions='0755'
        ))
        keyappend(cloudconf, "runcmd",'chkconfig --add /etc/init.d/cw-alarm;service cw-alarm start')

    if bash_files:
        if add_trap_file:
            put_files.append(trap_signals_file())
            put_files.append(wait_signals_file())
        if env_vars:
            put_files.append(env_file(env_vars))
        for b in bash_files:
            script_filename = "/%s.sh" % os.path.basename(b)
            put_files.append(dict(
                content= literal_unicode("".join(read_file(b))),
                path = script_filename,
                permissions = '0555'
            ))
            keyappend(cloudconf,"runcmd", script_filename)

    messages = MIMEMultipart()
    if len(put_files) > 0:
        cloudconf.update(dict(write_files = put_files))
    if len(cloudconf) > 0:
        add_cloudconf(messages, "cloudconf.txt", cloudconf)

    cloudconf_userdata = "".join(["#cloud-config","\n",str(yaml.dump(cloudconf))])
    return Base64(Sub(cloudconf_userdata, **svals))


#TODO: add awslogs starting calls
def userdata(
        script_files,
        resource_name,
        log_group,
        extra_vars            = [],
        hash_bang             = "#!/bin/bash -xeu\n",
        signal_traps          = True,
        setup_cloudwatch_logs = True,
        signal_url            = None):

    module_path = os.path.dirname(os.path.abspath(__file__))
    data = [
        hash_bang,
        'STACK_NAME=',    Ref("AWS::StackId"),'\n',
        'STACK_REGION=',  Ref("AWS::Region"),'\n',
        'RESOURCE_NAME=', resource_name,'\n',
        'LOG_GROUP=',     log_group,'\n',
    ]
    if signal_url:
        data.extend(['SIGNAL_URL=\'', signal_url, '\'\n'])
    data.extend(extra_vars)
    scripts = []
    if signal_traps:
        scripts.append(module_path+"/userdata/signal_traps.sh")
    if setup_cloudwatch_logs:
        scripts.append(module_path+"/userdata/awslog.sh")

    scripts.extend(script_files)

    if signal_url:
        scripts.append(module_path+"/userdata/signal_url.sh")


    for script_file in scripts:
        data.extend(read_file(script_file))

    return Base64(Join("", data))
