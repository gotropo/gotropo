#!/usr/bin/env python
from troposphere import Template, ImportValue, Ref
from troposphere.cloudformation import WaitConditionHandle, WaitCondition
from troposphere.cloudformation import Metadata, InitConfigSets, Init, InitConfig
from troposphere import ec2
import argparse
import sys
import create.config
from create import ec2 as create_ec2
from create import iam as create_iam

def run_userdata(ops, cf_ops, userdata_file):
    template = Template()
    template.add_version("2010-09-09")

    # assign a description using the value from the config file
    template.add_description(
            " ".join([ops.app_name,"cloudformation created by troposphere"]),
            )

    stack_name     = ops.app_name
    deploy_bucket  = ops.deploy_bucket
    deploy_env     = ops.deploy_env
    blank_ami_id   = ops.ami_image
    subnet         = ImportValue(ops.app_name+"AppSubnetIDAz0")
    sec_grps       = [ImportValue(ops.app_name+"AppSecurityGroupID")]
    log_group_name = ops.log_group
    cf_ops.cf_params = create.meta.params(template, ops.cf_params)

    roles = [
        create_iam.bucket_permission(deploy_bucket, deploy_env),
        create_iam.bucket_permission_read_only(deploy_bucket, "deploy/src"),
        create_iam.logwatch_permission(log_group_name),
        create_iam.ecr_get_auth_token(),
    ]
    instance_profile = create_iam.ec2_profile(template, stack_name+"RunUserdataIam", roles)

    #TODO: move
    userdata_vars = {k:ops.get(v) for k,v in ops.userdata_exports.items()}

    build_ec2_wait_handle = template.add_resource(WaitConditionHandle("buildEc2Wait"))
    userdata_vars.update(dict(
        success_signal = Ref(build_ec2_wait_handle),
    ))


    build_ec2_wait = template.add_resource(
        WaitCondition(
            "buildEc2WaitCondition",
            Handle=Ref(build_ec2_wait_handle),
            Timeout="900",
        )
    )
    ec2_instance = template.add_resource(
        ec2.Instance(
            stack_name+"RunOnce",
            ImageId = blank_ami_id,
            UserData = create_ec2.multipart_userdata(
                bash_files       = [userdata_file],
                install_packages = ["docker"],
                sub_values       = userdata_vars,
                add_trap_file    = False,
            ),
            InstanceType = "t2.small",
            SubnetId = subnet,
            SecurityGroupIds = sec_grps,
            IamInstanceProfile = instance_profile,
        )
    )
    print(template.to_json())

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('config_file', action='store',
            help="Path to yaml config file")
    parser.add_argument('userdata_file', action='store',
            help="Path to userdata to run on an ec2 instance")
    arg_values = parser.parse_args()
    ops    = create.config.parse(config_file = arg_values.config_file)
    cf_ops = create.config.ConfigOptions()
    run_userdata(ops, cf_ops, arg_values.userdata_file)
