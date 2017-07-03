#!/usr/bin/env python

import sys
import os.path
from functools import partial
import click
import boto3
import create.config
from create.custom_funcs import check_custom_func, check_lambda_code
from create.events import check_s3trigger_lambda
from botocore.exceptions import ClientError
from collections import OrderedDict, namedtuple

class BotoHandle(object):
    def __init__(self):
        self.bclient = {}

    def set_region(self, aws_region):
        self.aws_region = aws_region

    def create_client(self, aws_region, service_name):
        self.bclient[service_name] = boto3.client(service_name, region_name = aws_region)

    def get_client(self, service_name):
        if self.bclient.get(service_name):
            return self.bclient[service_name]
        else:
            if self.aws_region:
                self.create_client(self.aws_region, service_name)
                return self.bclient[service_name]
            else:
                raise ValueError("AWS Region not set on boto client")

    def get_cf_client(self):
        return self.get_client('cloudformation')

    def get_s3_client(self):
        return self.get_client('s3')

botohandle = BotoHandle()

def wait_for_stack(stack_name, wait_status):
    bclient = botohandle.get_cf_client()
    waiter  = bclient.get_waiter(wait_status)
    print("Waiting for %s to be in state %s" % (stack_name, wait_status))
    waiter.wait(StackName=stack_name)


def get_available_stacks():
    from create.stacks import (
        resources_stack_template,
        network_stack_template,
        app_stack_template,
        tcp_stack_template,
        build_stack_template
    )
    available_stacks = OrderedDict()
    stack_call = partial(dict, inbuilt = False, default=False, options=dict())

    #TODO: change stack_exec to not need inbuilt flag and can treat all stacks the same
    available_stacks['resources'] = dict(
        create_func = resources_stack_template,
        default = True,
        inbuilt = True,
        options = dict(Capabilities = ["CAPABILITY_IAM"])
    )
    available_stacks['network'] = stack_call(create_func = network_stack_template, default = True, inbuilt = True)
    available_stacks['app']     = stack_call(create_func = app_stack_template, default = True, inbuilt = True)
    available_stacks['build']   = stack_call(create_func = build_stack_template, inbuilt = True)
    available_stacks['mongodb'] = stack_call(create_func = tcp_stack_template, options = dict(Capabilities = ["CAPABILITY_IAM"]))
    available_stacks['rds']     = stack_call(create_func = tcp_stack_template)
    available_stacks['ec2']     = stack_call(create_func = tcp_stack_template)
    available_stacks['ec2_windows'] = stack_call(create_func = tcp_stack_template)
    available_stacks['efs'] = stack_call(create_func=tcp_stack_template)

    return available_stacks


def get_required_command(stack_name):
    ready_stacks = dict(
        stack_exists          = (["CREATE_COMPLETE", "ROLLBACK_COMPLETE", "UPDATE_COMPLETE","UPDATE_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE"], "update"),
        stack_removed         = (["DELETE_COMPLETE"], "create")
    )
    wait_required = dict(
        stack_create_complete = (["CREATE_IN_PROGRESS", "REVIEW_IN_PROGRESS"], "update"),
        stack_update_complete = ([ "ROLLBACK_IN_PROGESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_IN_PROGRESS", "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_ROLLBACK_IN_PROGRESS"], "update"),
        stack_delete_complete = (["DELETE_IN_PROGRESS"], "create")
    )

    bclient = botohandle.get_cf_client()


    try:

        stack_details = bclient.describe_stacks(StackName=stack_name)
        stack_status = stack_details['Stacks'][0]['StackStatus']
        for (key, status_codes) in ready_stacks.items():
            if stack_status in ready_stacks[key][0]:
                return ready_stacks[key][1]

        for (key, status_codes) in wait_required.items():
            if stack_status in wait_required[key][0]:
                wait_for_stack(stack_name, key)
                return wait_required[key][1]

        raise ValueError("Stack status not recognised")

    except ClientError:
        return "create"

    #Should not be here
    raise ValueError("Error finding status of existing stack")

def get_stack_parameter_keys(stack_name):
    bclient = botohandle.get_cf_client()

    #This will raise error on non existent stack
    stack_details = bclient.describe_stacks(StackName=stack_name)
    if stack_details['Stacks'][0].get('Parameters'):
        stack_params = stack_details['Stacks'][0]['Parameters']
        param_keys = [param['ParameterKey'] for param in stack_params]
        return param_keys
    else:
        return []

def set_cf_params(stack_name, use_params):
    param_keys = get_stack_parameter_keys(stack_name)
    for p in use_params:
        param_keys.remove(p)
    use_params_opt = [{'ParameterKey':k,'UsePreviousValue':True} for k in param_keys]
    return use_params_opt


def upload_template(stack_name, template, bucket, deploy_env, s3_filename=None):
    if s3_filename:
        obj_key = "%s/%s" % (deploy_env, s3_filename)
    else:
        obj_key = "%s/%s" % (deploy_env, stack_name)
    template_url = "s3://{bucket}/{obj_key}".format(bucket=bucket, obj_key = obj_key)
    print("Uploading template to {url}".format(url=template_url))
    bclient = botohandle.get_s3_client()
    bclient.put_object(Bucket=bucket, Key=obj_key, Body=template.to_json())
    #TODO: check upload success

def create_stack(stack_name, stack_type, aws_region, template, bucket, deploy_env):

    upload_template(stack_name, template, bucket, deploy_env)

    bclient = botohandle.get_cf_client()

    template_url = "https://s3-%s.amazonaws.com/%s/%s/%s" % (aws_region, bucket, deploy_env, stack_name)
    stack_exec_options = get_available_stacks()[stack_type]['options']

    print("creating stack:%s" % (stack_name,))
    bclient.create_stack(StackName = stack_name, TemplateURL = template_url, **stack_exec_options)

    wait_for_stack(stack_name, 'stack_create_complete')

def update_stack(stack_name, stack_type, aws_region, template, bucket, deploy_env, use_params = None, force = False):
    if force or click.confirm("Continue updating existing stack {stack_name} in {aws_region}?".format(stack_name = stack_name, aws_region = aws_region)):

        upload_template(stack_name, template, bucket, deploy_env)

        bclient = botohandle.get_cf_client()

        stack_exec_options = get_available_stacks()[stack_type]['options']
        if stack_exec_options.get('Parameters'):
            raise(ValueError,"Parameters option should not be set somewhere else")
        stack_exec_options['Parameters'] = set_cf_params(stack_name, use_params)
        template_url = "https://s3-%s.amazonaws.com/%s/%s/%s" % (aws_region, bucket, deploy_env, stack_name)

        print("updating stack %s" % stack_name)
        bclient.update_stack(StackName = stack_name, TemplateURL = template_url, **stack_exec_options)
        wait_for_stack(stack_name, 'stack_update_complete')

def to_stdout(template):
    print(template.to_json())

def stack_exec(stacks, config_file, dry_run = False, force = False, use_params = None):

    bin_path   = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(bin_path, "..")

    ops = create.config.parse(config_file = os.path.realpath(config_file))
    botohandle.set_region(ops.aws_region)
    aws_region    = ops.aws_region
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env

    func_opts = dict(
        aws_region = aws_region,
        bucket     = deploy_bucket,
        deploy_env = deploy_env,
    )
    commands = dict(
        create = dict(exec_function = create_stack, func_opts = func_opts),
        update = dict(exec_function = update_stack, func_opts = dict(use_params = use_params, force=force, **func_opts)),
        stdout = dict(exec_function = to_stdout,    func_opts = dict())
    )
    available_stacks = get_available_stacks()

    if not dry_run:
        #TODO: move to check all lambda code function
        check_files = []
        if ops.build_ami:
            check_files.append("ami_resource")
        if ops.cloudwatch_alarm:
            check_files.append("cloudwatch_alarm")

        if "mongo" in stacks:
            check_lambda_code(
                s3_bucket   = deploy_bucket,
                s3_prefix   = deploy_env,
                lambda_file = os.path.join(local_path,"/lambdas/mongo_start_stop_lambda.py")
            )

        if ops.get("s3_triggers") and "resources" in stacks:
            check_files.append("s3trigger")
            for trigger_name,trigger_setup in ops.s3_triggers.items():
                check_s3trigger_lambda(
                    deploy_bucket,
                    deploy_env,
                    trigger_setup['lambda_code'],
                )

        for lambda_file in check_files:
            check_custom_func(
                deploy_bucket    = deploy_bucket,
                deploy_env       = deploy_env,
                custom_func_file = lambda_file,
            )

    for s in stacks:
        inbuilt_stack_types = [key for key,value in available_stacks.items() if value['inbuilt']]
        defined_stacks = []
        if ops.get('tcpstacks'):
            defined_stacks = [k for k in ops.tcpstacks.keys()]
            for d in defined_stacks:
                if d in inbuilt_stack_types:
                    raise(ValueError("Stack name {} overrides value of a stack type.\
                        Currently unsupported to have stack key the same as a stack type".format(d)))
        if s not in inbuilt_stack_types + defined_stacks:
            raise(ValueError("Stack \"{}\" not a valid stack type. Available types:{}".format(s, inbuilt_stack_types + defined_stacks)))

        stack_name = "{stack}-{stack_type}".format(stack=ops.app_name, stack_type=s)
        if  available_stacks.get(s):
            stack_type = s
            stack_template = available_stacks[stack_type]['create_func'](ops, dry_run)
        else:
            stack_type = ops.tcpstacks[s]['stack_type']
            if not ops.tcpstacks[s]['enabled']:
                print("Stack {} not enabled. Skipping.".format(s), file = sys.stderr)
                continue
            stack_template = available_stacks[stack_type]['create_func'](ops, s, ops.tcpstacks[s], dry_run)

        if dry_run:
            command = 'stdout'
            command_options = dict(template=stack_template,**commands[command]['func_opts'])
        else:

            command = get_required_command(stack_name)
            command_options = dict(
                stack_name = stack_name,
                stack_type = stack_type,
                template=stack_template,
                **commands[command]['func_opts']
            )

        commands[command]['exec_function'](**command_options)

@click.group()
def go_tropo():
    pass

@go_tropo.command()
@click.option('--dry-run', is_flag=True)
@click.option('--run', is_flag=True)
@click.argument('config_yaml', nargs = 1)
def build(dry_run, run, config_yaml):
    #TODO:see if this can be moved to use stack_exec
    ops = create.config.parse(config_file = os.path.realpath(config_yaml))
    app_cfn_options = create.config.ConfigOptions()
    botohandle.set_region(ops.aws_region)
    template = get_available_stacks()['build']['create_func'](ops, dry_run)

    stack_name = ops.app_name+"-build"

    if dry_run:
        if run:
            print("Ignoring --run option since --dry-run was given", file=sys.stderr)
        to_stdout(template = template)
    elif run:
        print("Creating build stack")
        create_stack(
            stack_name = stack_name,
            stack_type = "build",
            aws_region = ops.aws_region,
            bucket     = ops.deploy_bucket,
            deploy_env = ops.deploy_env,
            template   = template
        )
    else:
        upload_template(
            stack_name = stack_name,
            template   = template,
            bucket     = ops.deploy_bucket,
            deploy_env = ops.deploy_env,
            s3_filename= ops.build_stack_file
        )


@go_tropo.command()
@click.option("--stream", help="Only show logs for given stream")
@click.argument('config_yaml', nargs = 1)
def logs(stream, config_yaml):
    import create.stacks
    from awslogs import AWSLogs
    ops = create.config.parse(config_file = os.path.realpath(config_yaml))
    aws_region = ops.aws_region
    log_group = create.stacks.create_resource_names(ops)['log_group']
    if not stream:
        log_stream_name = "ALL"
    else:
        log_stream_name = stream
    al = AWSLogs(
        output_group_enabled=True,
        watch=True,
        aws_region = aws_region,
        log_stream_name = log_stream_name,
        start="20m",
        output_stream_enabled=True,
        log_group_name=log_group,
        color_enabled=True
    )
    al.list_logs()

@go_tropo.command()
@click.option('--stack', help="Only create named stack section", multiple = True)
@click.option('--use-param', help="If updating existing stack, use default Cloudformation parameter from config file", multiple = True)
@click.option('--dry-run', is_flag=True)
@click.option('--force', is_flag=True)
@click.argument('config_yaml', nargs = 1)
def deploy(stack, use_param, dry_run, force, config_yaml):

    if not stack:
        available_stacks = get_available_stacks()
        stack = [s for s in available_stacks.keys() if available_stacks[s]['default']]

    if dry_run:
        print("Dry run create stacks:%s" % (stack,), file=sys.stderr)
        stack_exec(stacks = stack, config_file = config_yaml, dry_run = True)
    else:
        stack_exec(stacks = stack, config_file = config_yaml, use_params = use_param, force = force)

@go_tropo.command()
def create_yaml():
    pass
