import troposphere
import troposphere.ec2 as ec2
import troposphere.awslambda as awslambda
from troposphere.iam import InstanceProfile
from troposphere import Template, Ref, Base64, Join, GetAtt, Retain, Tags
from troposphere import ImportValue
from troposphere.iam import Role, Policy
from troposphere.cloudformation import WaitCondition, WaitConditionHandle
from troposphere.cloudformation import AWSCustomObject
from . import ec2 as create_ec2
from . import custom_funcs
from . import iam
from create import export_ref, import_ref

class MakeAmi(AWSCustomObject):
    resource_type = "Custom::MakeAmi"
    props = {
        'ServiceToken': (str, True),
        'StackName'   : (str, True),
        'AutoScaleGrp': (str, True),
        'AwsRegion'   : (str, True),
    }

def build_ami_role(template, ops, app_cfn_options):
    app_name = ops.app_name

    lambda_exec_role = template.add_resource(
       Role(
           app_name + "LambdaExecutionRole",
           Policies=[
               Policy(
                   PolicyName="LambdaCustomResourceTest",
                   PolicyDocument={
                       "Version": "2012-10-17",
                       "Statement": [
                           {
                               "Action": ["logs:*"],
                               "Resource": "arn:aws:logs:*:*:*", #TODO: lock down to its own logs
                               "Effect": "Allow"
                           },
                           {
                               "Action": [
                                   "ec2:CreateImage",
                                   "ec2:DeregisterImage",
                                   "ec2:DescribeImages",
                                   "ec2:CreateTags",
                                   ],
                               "Resource": "*", #Lock down currently not possible in AWS
                               "Effect": "Allow"
                           },
                           {
                               "Action": [
                                   "autoscaling:DescribeAutoScalingGroups",
                                   "autoscaling:UpdateAutoScalingGroup"
                                ],
                               "Resource": "*",
                               "Effect": "Allow"
                           }
                           ]
                    }),
               ],
           AssumeRolePolicyDocument={"Version": "2012-10-17", "Statement": [
               {"Action": ["sts:AssumeRole"], "Effect": "Allow",
               "Principal": {"Service": ["lambda.amazonaws.com"]}}]},
       )
    )
    export_ref(
        template,
        app_cfn_options.resource_names['build_ami_role'],
        GetAtt(lambda_exec_role, "Arn"),
        "ARN of Role for lambda AMI creation"
    )
    return lambda_exec_role

def ec2_amibuild_profile(template, ops, app_cfn_options):
    app_name      = ops.app_name
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env
    log_group     = app_cfn_options.resource_names['log_group']
    profile_name  = app_cfn_options.resource_names['ec2_amibuild_profile']

    ec2_amibuild_role = iam.app_role(deploy_bucket, deploy_env, log_group)
    ec2_amibuild_role.append(iam.ami_readonly())
    ec2_amibuild_profile = iam.ec2_profile(template, profile_name, ec2_amibuild_role)
    export_ref(
        template,
        profile_name,
        ec2_amibuild_profile,
        "Role for ami build instance"
    )
    return ec2_amibuild_profile


def build_ami(template, ops, app_cfn_options):
    stack_name       = ops.app_name
    deploy_bucket    = ops.deploy_bucket
    deploy_env       = ops.deploy_env
    billing_id       = ops.billing_id
    elb_name         = app_cfn_options.elb_name
    key_name         = app_cfn_options.cf_params.get('KeyName')
    userdata_file    = ops.userdata_file
    blank_ami_id     = ops.ami_image
    root_volume_size = ops.root_volume_size
    subnet           = app_cfn_options.app_subnets[0]
    sec_grps         = app_cfn_options.app_sg
    install_packages = ops.install_packages
    autoscale_name   = app_cfn_options.autoscale_name
    lambda_exec_role = app_cfn_options.resource['build_ami_role']

    log_group        = app_cfn_options.resource_names['log_group']

    ami_instance_profile = app_cfn_options.resource['ec2_amibuild_profile']

    build_ami_lambda = custom_funcs.custom_resource(
        template,
        "BuildAmi",
        deploy_bucket = deploy_bucket,
        deploy_env    = deploy_env,
        lambda_file   = "ami_resource",
        iam_role      = lambda_exec_role,
    )

    build_autoscale_name = "".join([stack_name,"AmiBuild"])
    lc_name = "".join([stack_name,"AmiBuildLaunchConfig"])

    ami_userdata = create_ec2.app_userdata(ops, app_cfn_options, build_autoscale_name)

    as_grp = create_ec2.autoscale(
        template,
        build_autoscale_name,
        lc_name     = lc_name,
        env         = deploy_env,
        app_name    = stack_name,
        key_name    = key_name,
        sec_grp     = sec_grps,
        iam_profile = ami_instance_profile,
        billing_id  = billing_id,
        subnets     = [subnet],
        userdata    = ami_userdata,
        elbs        = [],
        image       = blank_ami_id,
        set_min_size= 1,
        set_max_size= 1,
        root_volume_size = root_volume_size,
    )

    make_ami = template.add_resource(
        MakeAmi(
            stack_name + "MakeAmi",
            ServiceToken = GetAtt(build_ami_lambda,"Arn"),
            StackName    = Ref("AWS::StackId"),
            AutoScaleGrp = Ref(as_grp),
            AwsRegion    = Ref("AWS::Region"),
            DependsOn    = build_autoscale_name,
        )
    )

    #new ami is
    return GetAtt(stack_name + "MakeAmi","ImageId")
