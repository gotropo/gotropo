import boto3
from troposphere.iam import Role, Policy
from troposphere import AWSObject, GetAtt, Join, Ref
from troposphere import awslambda
import awacs.sns
import awacs.cloudwatch
import awacs.logs as logs
from . import route53
from . import iam
from . import custom_funcs
from create import export_ref, import_ref

#TODO: move this
class SnsTopicCustom(AWSObject):
    resource_type = "Custom::SnsTopicUsEast1"
    props = {
        'ServiceToken': (str, True),
        'SnsTopicName': (str, True),
        'Contacts' : ([str], True),
    }
#TODO: move this
class CloudwatchAlarmCustom(AWSObject):
    resource_type = "Custom::CloudWatchAlarmUsEast1"
    props = {
        'ServiceToken': (str, True),
        'AlarmName': (str, True),
        'HealthCheckId' : (str, True),
        'TopicArn' : (str, True),
    }

def health_check_iam(template, ops, app_cfn_options):
    app_name = ops.app_name

    self_log_action = iam.make_statement(
        actions = [logs.Action("*")],
        resources = ["arn:aws:logs:*:*:/aws/lambda/" + app_name + "*"],
    )
    cloudwatch_alarm_role = [
        self_log_action,
        iam.make_statement(
            actions = [
                awacs.cloudwatch.PutMetricAlarm,
                awacs.cloudwatch.ListMetrics,
                awacs.cloudwatch.DeleteAlarms,
                awacs.cloudwatch.DescribeAlarms,
                awacs.cloudwatch.EnableAlarmActions,
             ],
            resources = ["*"],
        )
    ]

    cloudwatch_alarm_lambda_iam = custom_funcs.lambda_iam(template,
        "CloudwatchAlarmRole",
        cloudwatch_alarm_role,
    )

    export_ref(
        template,
        app_cfn_options.resource_names['cloudwatch_alarm_role'],
        GetAtt(cloudwatch_alarm_lambda_iam, "Arn"),
        "ARN of Role for lambda Cloudwatch alerts"
    )
    return cloudwatch_alarm_role

#Needed to use custom lambda resource to create cross region resources
def health_check_setup(
        template,
        stack_name,
        aws_region,
        deploy_bucket,
        deploy_env,
        check_domain,
        check_location,
        sns_topic_arn,
        cloudwatch_alarm_lambda_iam,
        dry_run = False,
        ):
    """
    Use lambda custom resources to create cloudwatch alarms to notify with
    SMS alerts on health of app
    """
    health_check_lambda = "cloudwatch_alarm"

    cloudwatch_alarm = custom_funcs.custom_resource(
        template,
        "CloudWatchAlarmResource",
        deploy_bucket = deploy_bucket,
        deploy_env = deploy_env,
        lambda_file = "cloudwatch_alarm",
        iam_role = cloudwatch_alarm_lambda_iam,
    )

    check_app = route53.health_check(
        template,
        "".join([stack_name,"HealthCheck"]),
        fqdn = check_domain,
        location = check_location
    )

    cloudwatch_alarm_health_check = template.add_resource(
        CloudwatchAlarmCustom(
            stack_name + "CloudwatchAlarm",
            ServiceToken = GetAtt(cloudwatch_alarm, "Arn"),
            AlarmName = stack_name + "-" + aws_region,
            HealthCheckId = Ref(check_app),
            TopicArn = sns_topic_arn,
        )
    )

def health_check(template, ops, app_cfn_options):
    health_check_setup(
        template = template,
        stack_name = ops.app_name,
        aws_region = ops.aws_region,
        deploy_bucket = ops.deploy_bucket,
        deploy_env = ops.deploy_env,
        check_domain = ops.domain,
        check_location = ops.health_check_location,
        sns_topic_arn = ops.sns_topic_arn,
        cloudwatch_alarm_lambda_iam = app_cfn_options.resource['cloudwatch_alarm_role'],
        dry_run = False,
    )

