from troposphere import Ref,Sub,Base64, Template, Output, GetAtt, ImportValue, Export, ec2, Tags, route53
from troposphere.events import Rule, Target
from troposphere.cloudformation import WaitCondition, WaitConditionHandle
from troposphere.sns import Subscription
from troposphere import awslambda
from functools import partial
import argparse
import boto3
import json
import sys
from . import iam as create_iam
from . import custom_funcs
from . import tcpstacks
import awacs
import awacs.logs as logs
import create.network
from create import export_ref, import_ref


def mongo_userdata(db_type, db_name, ops, app_cfn_options, db_ips, userdata_file):

    cf_param_refs = {k:v for k,v in app_cfn_options.cf_params.items()}
    userdata_vars = {k:ops.get(v) for k,v in ops.userdata_exports.items()}
    userdata_vars.update(cf_param_refs)
    userdata_vars.update(dict( LOG_GROUP        = app_cfn_options.log_group,
                               resource_name    = db_name))
    userdata_vars.update(dict( MONGO_TYPE       = db_type))
    userdata_vars.update(db_ips)
    userdata_1 = create.ec2.multipart_userdata(
                        bash_files       = [userdata_file],
                        install_packages = ["docker"],
                        sub_values       = userdata_vars,
                        ip_list          = db_ips,
                    )
    return userdata_1

def add_instances(template, ops, app_cfn_options, db_name, db_type, instance_type, db_ips, userdata_file, az, previous_instance, fs_mounts):
    subnet      = app_cfn_options.mongo_subnets[az]
    iam_profile = ImportValue(app_cfn_options.resource_names['ec2_iam_profile'])

    ebs_volume = ec2.EBSBlockDevice( VolumeSize = "100", Encrypted = False, VolumeType = "gp2", DeleteOnTermination = True)
    bdm = ec2.BlockDeviceMapping( DeviceName = '/dev/sdf', Ebs = ebs_volume)
    ec2_instance_func = partial(
                            ec2.Instance,
                            db_name,
                            ImageId             = ops.ami_image,
                            InstanceType        = instance_type, #TODO: config option
                            KeyName             = app_cfn_options.cf_params.get('KeyName'),
                            SubnetId            = subnet,
                            AvailabilityZone    = ops.availability_zones[az],
                            IamInstanceProfile  = iam_profile,
                            Tags                = Tags(
                                 Name           = db_name,
                                 Env            = ops.deploy_env,
                                 BillingID      = ops.billing_id
                            ),
                            BlockDeviceMappings = [bdm],
                            SecurityGroupIds    = [GetAtt(app_cfn_options.mongo_sg_name,"GroupId")],
                            UserData            = mongo_userdata(db_type, db_name, ops, app_cfn_options, db_ips, userdata_file),
                        )
    if previous_instance:
        instance = template.add_resource(ec2_instance_func(DependsOn=previous_instance))
    else:
        instance = template.add_resource(ec2_instance_func())
    tcpstacks.create_disk_cloudwatch_alarm(  template, Ref(instance), db_name, ops.email_topic_arn, fs_mounts)
    tcpstacks.create_memory_cloudwatch_alarm(template, Ref(instance), db_name, ops.email_topic_arn)

def create_cloudwatch_rule(template, ops, app_cfn_options):
    mongo_inst_ids = dict()
    insta_id_list  = []
    for count,instance_names in enumerate(sorted(app_cfn_options.db_names)):
        insta_id = "".join(["INST_ID",str(count)])
        mongo_inst_ids[insta_id] = Ref(instance_names)
        insta_id_list.append("".join(["${",insta_id,"}"]))
    for action in ["Start","Stop"]:
        rule_name     = "".join(["CloudWatch",action,"Rule"])
        if( action == "Start" ):
            cron_patn = "cron(0 19 ? * 1-5 *)"
        else:
            cron_patn = "cron(0 7 ? * 2-6 *)"
        mongo_inst_ids.update(ACTION    = action, REGION = ops.aws_region)
        input_patn    = dict( Action    = "${ACTION}", Region = "${REGION}",
                              Instances = insta_id_list)
        input_pattern = json.dumps(input_patn, sort_keys=True)
        input_string  = Sub(input_pattern,**mongo_inst_ids)
        lambda_id     = "".join([ops.app_name,"MongoStartStopFunction"])
        lambda_target = Target( "LambdaTarget",
                            Arn   = app_cfn_options.lambda_arn,
                            Id    = lambda_id,
                            Input = input_string)
        cloudwatch_rule = template.add_resource(Rule( rule_name,
                                   Description          = "".join(["CloudWatch Event ",action," Rule for",ops.app_name," Mongo"]),
                                   ScheduleExpression   = cron_patn,
                                   State                = "ENABLED",
                                   Targets              = [lambda_target] ))
        invoke_name     = "".join(["MongoLambdaInvoke",action])
        lambda_invoke_permissions(template, invoke_name, app_cfn_options.lambda_arn, GetAtt(cloudwatch_rule,"Arn"))

def create_lambda_func(template, ops, app_cfn_options):
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env
    app_name      = ops.app_name

    self_log_action                 = create_iam.lambda_self_logging(app_name)
    lambda_mongo_start_stop_role    = [
                                        self_log_action,
                                        create_iam.make_statement(
                                            actions = [
                                            awacs.ec2.StartInstances,
                                            awacs.ec2.StopInstances,
                                            awacs.logs.CreateLogGroup,
                                            awacs.logs.CreateLogStream,
                                            awacs.logs.PutLogEvents,
                                            ],
                                            resources = ["*"],
                                        )
                                      ]
    lambda_mongo_start_stop_iam     = custom_funcs.lambda_iam(template, "LambdaCronRole", lambda_mongo_start_stop_role,)
    custom_funcs.check_lambda_code(ops.deploy_bucket, deploy_env, "./create_cloudformation/lambdas/mongo_start_stop_lambda.py", lib_files = [])
    lambda_func                     = custom_funcs.lambda_function(
                                                template,
                                                "LambdaCronResource",
                                                deploy_bucket = ops.deploy_bucket,
                                                local_file    = "./create_cloudformation/lambdas/mongo_start_stop_lambda.py",
                                                iam_role      = GetAtt(lambda_mongo_start_stop_iam,"Arn"),
                                                s3_prefix     =  deploy_env,
                                            )
    app_cfn_options.lambda_arn      = GetAtt(lambda_func,"Arn")

def lambda_invoke_permissions(template, name, lambda_arn, source_arn):
    template.add_resource(
        awslambda.Permission(
            name,
            FunctionName  = lambda_arn,
            Action        = "lambda:InvokeFunction",
            Principal     = "events.amazonaws.com",
            SourceArn     = source_arn,
        )
    )

def create_record_set(template, ops, app_cfn_options, mongo_dbs, dbconfig_ip, count):
    record_set      = mongo_dbs.split(":",1)[0]
    hosted_zone     = record_set.split(".",1)[1]
    rec_set_name    = "".join(["MongoRecordSet",str(count)])
    rec_set         = template.add_resource(route53.RecordSetType( rec_set_name,      Type = 'A',
                                                                   Name = record_set, TTL  = 300,
                                                                   HostedZoneName   = hosted_zone,
                                                                   ResourceRecords  = [dbconfig_ip]))

def mongo_stack(template, ops, app_cfn_options, stack_name, stack_setup):

    app_nets            = [val for key,val in sorted(ops.app_networks.items())]
    app_ports           = set([val[1] for key,val in ops.port_map.items()])
    cf_params           = app_cfn_options.cf_params
    stack_name          = stack_setup['stack_name']

    mongo_subnets       = dict()
    mongo_networks      = stack_setup['networks']
    mongo_ports         = stack_setup['ports']
    number_of_shards    = stack_setup['number_of_shards']
    custom_mongo_rules  = stack_setup['custom_rules']
    shard_userdata      = stack_setup['shards_userdata']
    config_userdata     = stack_setup['config_userdata']
    man_userdata        = stack_setup['man_userdata']
    mongo_dbs           = stack_setup['mongo_dbs']
    enableArbiter       = stack_setup['enableArbiter']
    fs_mounts           = stack_setup['fs_mounts']
    stack_resource_name = "".join([ops.app_name, stack_name])
    app_cfn_options.mongo_sg_name   = ops.app_name+"Sg"+stack_name
    mongo_nets                      = [val for key,val in sorted(mongo_networks.items())]

    for az,cidr in sorted(mongo_networks.items()):
        net_name            = "".join([ops.app_name,"Sn",stack_name,az])
        subnet              = create.network.subnet(template, ops.vpc_id, net_name, cidr, ops.availability_zones[az],ops.billing_id,ops.deploy_env)
        mongo_subnets[az]   = subnet
        create.network.routetable( template, ops.vpc_id, "Route"+net_name, subnet, nat_id = ops.nat_host_ids[az],
                                   vpn_id = ops.ofc_vpn_id, vpn_route = ops.vpn_route)
    mongo_nacl_factory      = create.network.AclFactory(
                                    template,
                                    name         = "".join([ops.app_name,"NetAcl",stack_name]),
                                    vpc_id       = ops.vpc_id,
                                    in_networks  = app_nets,
                                    in_ports     = mongo_ports,
                                    out_ports    = ops.out_ports,
                                    out_networks = app_nets,
                                    ssh_hosts    = ops.get("deploy_hosts"),
                                )
    export_ref(
            template,
            export_name = "".join([ops.app_name,"NetAcl",stack_name]),
            value       = Ref("".join([ops.app_name,"NetAcl",stack_name])),
            desc        = " {stack} NetAcl ".format(stack=stack_resource_name)
        )

    for count,az in enumerate(sorted(mongo_subnets.keys())):
        assoc_name      = stack_name+"AclAssoc"+az+str(count)
        subnet          = mongo_subnets[az]
        create.network.assoc_nacl_subnet(template, assoc_name, mongo_nacl_factory.nacl, subnet)

    mongo_sg            = create.network.sec_group(template,
                                                   name            = app_cfn_options.mongo_sg_name,
                                                   in_networks     = sorted(mongo_nets),
                                                   in_ports        = mongo_ports,
                                                   out_ports       = mongo_ports,
                                                   ssh_hosts       = ops.deploy_hosts,
                                                   custom_rules    = custom_mongo_rules,
                                                   ops             = ops,
                                                  )
    export_ref(
            template,
            export_name = app_cfn_options.mongo_sg_name,
            value       = mongo_sg,
            desc        = " {stack} Security Group".format(stack=stack_resource_name)
        )

    app_cfn_options.mongo_subnets = mongo_subnets

    if (number_of_shards% 2 == 0):
       pass
    else:
       print("Error: Number of Shards should be Even - ",ops.number_of_shards)
       sys.exit(1)

    app_cfn_options.shard_names = []
    app_cfn_options.db_names    = []
    db_ips                      = dict()
    previous_instance           = None

    ## Create Mongo Arbiter, Secondary and Primary Shard
    i = 1
    while(i <= (number_of_shards/2)):
      j = 2
      while(j >= 1):
        az = "az1"
        if( j == 1):
          shrad_type    = "PS"
        else:
          shrad_type    = "SS"
          if enableArbiter :
            az          = "az2"
            arbiter     = "".join([ops.app_name,"DBArbiter",str(i)])
            ip_name     = "".join(["AR",str(i),"IP"])
            add_instances(template, ops, app_cfn_options, arbiter, ip_name, "t2.micro", db_ips, shard_userdata, az, previous_instance, fs_mounts)
            previous_instance   = arbiter
            db_ips[ip_name]     = GetAtt(arbiter,"PrivateIp")

        shard_name          = "".join([ops.app_name,"DB",shrad_type,str(i),str(j)])
        app_cfn_options.db_names.append(shard_name)
        app_cfn_options.shard_names.append(shard_name)
        ip_name             = "".join([shrad_type,str(i),str(j),"IP"])
        add_instances(template, ops, app_cfn_options, shard_name, ip_name, "r4.large", db_ips, shard_userdata, az, previous_instance, fs_mounts)
        previous_instance   = shard_name
        db_ips[ip_name]     = GetAtt(shard_name,"PrivateIp")
        j -= 1
      i += 1

    ## Create Mongo Config
    cfg_count   = 1
    i           = 1
    db_ips["CFGRS"] = mongo_dbs.rstrip(',')
    mongo_dbs   = mongo_dbs.split(',')
    config_ip   = []
    if enableArbiter:
      cfg_count = 3
    while ( i <= cfg_count ):
      az                        = "".join(["az",str(i)])
      dbconfig                  = "".join(["dbconfig",az])
      dbconfig_name             = "".join([ops.app_name,"DBConfig",az])
      app_cfn_options[dbconfig] = dbconfig_name
      app_cfn_options.db_names.append(app_cfn_options[dbconfig])
      add_instances(template, ops, app_cfn_options, shard_name, ip_name, "r4.large", db_ips, shard_userdata, az,
                    previous_instance, fs_mounts)
      previous_instance                 = dbconfig_name
      db_ips["".join(["CFGIP",str(i)])] = GetAtt(dbconfig_name,"PrivateIp")
      config_ip.append(GetAtt(dbconfig_name,"PrivateIp"))
      create_record_set(template, ops, app_cfn_options, mongo_dbs[(i-1)], config_ip[(i-1)], i)
      i += 1



    ## Create Mongo Man
    man_count   = 1
    i           = 1
    if enableArbiter:
      man_count = 2
    while ( i <= man_count ):
      az        = "".join(["az",str(i)])
      dbman     = "".join([ops.app_name,"DBMan",az])
      app_cfn_options.db_names.append(dbman)
      add_instances(template, ops, app_cfn_options, dbman, "Man", "m3.large", db_ips, man_userdata, az, previous_instance, fs_mounts)
      previous_instance                 = dbman
      db_ips["".join(["MANIP",str(i)])] = GetAtt(dbman,"PrivateIp")
      i += 1

    if not enableArbiter:
      app_cfn_options.dbconfig = dbconfig_name
      create_lambda_func(template, ops, app_cfn_options)
      create_cloudwatch_rule(template, ops, app_cfn_options)
