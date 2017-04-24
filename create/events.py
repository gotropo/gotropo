#import troposphere.awslambda as awslambda
from functools import partial
from troposphere.cloudformation import AWSCustomObject
from troposphere import Ref, GetAtt
from awacs.aws import Action
from . import iam as create_iam
from . import custom_funcs

class S3Trigger(AWSCustomObject):
    resource_type = "Custom::S3Trigger"
    props = {
        'ServiceToken': (str, True), #Lambda that will create trigger
        'StackName'   : (str, True),
        'AwsRegion'   : (str, True),
        'BucketName'  : (str, True),
        'LambdaARN'   : (str, True), #Lambda that created trigger will call
        'Prefix'      : (str, True),
        'Suffix'      : (str, False),
        'EnvVars'     : (str, False),
    }

def s3trigger_role(template, ops, trigger_name):
    app_name      = ops.app_name
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env
    aws_region    = ops.aws_region
    account_id    = ops.account_id

    trigger_setup = ops.s3_triggers[trigger_name]

    deploy_dest = ops.get("build_dest")

    supported_roles = dict(
            source_read           = (create_iam.bucket_permission_read_only, dict(deploy_bucket = deploy_bucket, source_prefix = trigger_setup['prefix'])),
            bucket_permissions    = (create_iam.bucket_permission, dict(deploy_bucket = deploy_bucket, deploy_env = deploy_env, deploy_dest = deploy_dest)),
            cloudformation_new    = (create_iam.cloudformation_new, dict(deploy_bucket = deploy_bucket, aws_region = aws_region, deploy_env = deploy_env, app_name = app_name)),
            cloudformation_update = (create_iam.cloudformation_update, dict(deploy_bucket = deploy_bucket, aws_region = aws_region, deploy_env = deploy_env, app_name = app_name, stack_type="app")),
            pass_role             = (create_iam.pass_role, dict(account_id = account_id, app_name = app_name)),
            autoscale_full        = (create_iam.autoscale_full, dict()),
            elb_read              = (create_iam.elb_read, dict()),
            cloudwatch_metrics    = (create_iam.cloudwatch_metrics, dict()),
            ec2_full              = (create_iam.ec2_full, dict()),
            lambda_invoke         = (create_iam.lambda_invoke, dict()),
        )

    self_log_action = create_iam.lambda_self_logging(app_name)
    lambda_roles = [self_log_action] #TODO: add extra roles here
    for role in trigger_setup['preset_roles']:
        make_role = supported_roles.get(role)
        if make_role:
            add_role = make_role[0](**make_role[1])
            if type(add_role) is list:
                lambda_roles.extend(add_role)
            else:
                lambda_roles.append(add_role)
        else:
            raise(ValueError(
                "Role {} not supported in preset roles. Supported roles:{}".format(
                    role,','.join([i for i in supported_roles.keys()]))
                )
            )
    cs = trigger_setup.get('custom_roles')
    if cs:
        for role_name, role_values in cs.items():
            lambda_roles.append(create_iam.make_statement(
                    actions = [Action(*r) for r in role_values['actions']],
                    resources = role_values['resources']
                )
            )

    lambda_iam = custom_funcs.lambda_iam(template,
        trigger_name+"Role",
        lambda_roles,
    )

    return lambda_iam

def s3trigger_custom_resource_role(template, app_name, deploy_bucket, deploy_env):
    self_log_action = create_iam.lambda_self_logging(app_name)
    bucket_permission = create_iam.bucket_permission(deploy_bucket, deploy_env)
    notif_permission = create_iam.notification_permission(deploy_bucket)
    lambda_role = [self_log_action,bucket_permission, notif_permission]
    lambda_iam = custom_funcs.lambda_iam(template,
        "makeS3triggerRole",
        lambda_role,
    )

    return lambda_iam

def s3trigger_custom_resource(template, app_name, deploy_bucket, deploy_env):
    make_s3triggers_role = s3trigger_custom_resource_role(template, app_name, deploy_bucket, deploy_env)

    return custom_funcs.custom_resource(
        template,
        "MakeS3Triggers",
        deploy_bucket = deploy_bucket,
        deploy_env    = deploy_env,
        lambda_file   = "s3trigger",
        iam_role      = GetAtt(make_s3triggers_role, "Arn"),
    )

def s3triggers_prefix(deploy_env):
    return deploy_env+"/s3triggers"

def check_s3trigger_lambda(deploy_bucket, deploy_env, local_file):
    s3_prefix = s3triggers_prefix(deploy_env)
    custom_funcs.check_lambda_code(
        s3_bucket   = deploy_bucket,
        s3_prefix   = s3_prefix,
        lambda_file = local_file,
    )

def s3triggers(template, ops, app_cfn_options):
    app_name      = ops.app_name
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env
    aws_region    = ops.aws_region

    make_s3trigger = s3trigger_custom_resource(template, app_name, deploy_bucket, deploy_env)

    previous_trigger = None
    for trigger_name,trigger_setup in ops.s3_triggers.items():
        #create triggered lambda role
        lambda_iam = s3trigger_role(
            template = template,
            trigger_name = trigger_name,
            ops = ops,
        )

        #lambda code currently uploaded to s3 by go-tropo.py

        #create lambda
        opts = dict(
            template      = template,
            name          = trigger_name,
            deploy_bucket = deploy_bucket,
            s3_prefix     = s3triggers_prefix(deploy_env),
            local_file    = trigger_setup['lambda_code'],
            iam_role      = GetAtt(lambda_iam,"Arn"),
        )
        if trigger_setup.get('environment_setup'):
            opts['env_vars'] = trigger_setup['environment_setup']
        if trigger_setup.get('handler'):
            opts['handler'] = trigger_setup.handler
        lambda_function_ref = custom_funcs.lambda_function(**opts)
        invoke_perm_name = trigger_name+"Invoke"
        invoke_perms = custom_funcs.s3_invoke_permissions(template, invoke_perm_name, deploy_bucket, lambda_function_ref)

        trigger_resource_name = app_name + "S3Trigger" + trigger_name
        make_trigger_function_call = partial(
            S3Trigger,
            trigger_resource_name,
            ServiceToken = GetAtt(make_s3trigger, "Arn"),
            StackName    = app_name,
            DependsOn    = invoke_perm_name,
            AwsRegion    = aws_region,
            BucketName   = deploy_bucket,
            LambdaARN    = GetAtt(lambda_function_ref, "Arn"),
            Prefix       = trigger_setup['prefix'],
            Suffix       = trigger_setup['suffix'],
        )
        #set trigger to call lambda function
        #Call custom resource:
        if previous_trigger:
            s3trigger = template.add_resource(
                make_trigger_function_call(DependsOn=previous_trigger)
            )
        else:
            s3trigger = template.add_resource(
                make_trigger_function_call()
            )
        previous_trigger = trigger_resource_name
