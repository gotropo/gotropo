from troposphere import Ref
from troposphere import iam
import awacs.ec2, awacs.cloudformation, awacs.iam
import awacs.autoscaling, awacs.elasticloadbalancing, awacs.ec2
import awacs.awslambda
import awacs.sts, awacs.aws
import awacs.elasticloadbalancing
from awacs.aws import Action
import awacs.sts
import awacs.s3 as s3
import awacs.ecs as ecs
import awacs.ecr as ecr
import awacs.logs as logs
import awacs.cloudwatch as cloudwatch
from troposphere import Base64, FindInMap, GetAtt, Join, Output
from create import export_ref, import_ref
import os.path

def make_statement(actions, resources, effect = awacs.aws.Allow, condition = None):
    opts = dict(
        Action    = actions,
        Resource  = resources,
        Effect    = effect,
    )
    if condition:
        opts['Condition'] = condition
    return awacs.aws.Statement(**opts)

def make_assume_role(name, principals, role_statement):
    assume_statement = awacs.aws.Statement(
        Action    = [awacs.sts.AssumeRole],
        Principal = awacs.aws.Principal("Service", principals),
        Effect    = awacs.aws.Allow,
    )
    return iam.Role(
        name,
        AssumeRolePolicyDocument=awacs.aws.Policy(
            Statement = [assume_statement]
        ),
        Policies = [iam.Policy(
            PolicyName     = name.lower(),
            PolicyDocument = awacs.aws.Policy(
                Statement = role_statement
            )
        ),]
    )

def autoscale_full():
    afull = make_statement(
        actions = [
            awacs.autoscaling.Action("*"),
        ],
        resources = ["*"],
    )
    return afull

def build_stack_profile(template, ops, app_cfn_options):
    app_name      = ops.app_name
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env
    log_group     = app_cfn_options.resource_names['log_group']
    roles = [
        bucket_permission(deploy_bucket, deploy_env),
        bucket_permission_read_only(deploy_bucket, "deploy/"+deploy_env),
        logwatch_permission(log_group),
        get_ecr_image()
    ]
    instance_profile = ec2_profile(template, app_name+"BuildStackIam", roles)
    export_ref(
        template,
        export_name = app_cfn_options.resource_names['build_stack_profile'],
        value = instance_profile,
        desc = "Role used by stack that builds deployable files from source"
    )

def ec2_profile(template, name, role_statement):

    cfnrole = template.add_resource(
        make_assume_role(
            name,
            principals = ["ec2.amazonaws.com"],
            role_statement = role_statement,
        )
    )

    cfn_instance_profile = template.add_resource(iam.InstanceProfile(
        name+"InstanceProfile",
        Roles =[Ref(cfnrole)],
    ))

    return Ref(cfn_instance_profile)

def ecs_task_role(template, name, role_statement):

    cfnrole = template.add_resource(
        make_assume_role(
            name,
            principals = ["ecs-tasks.amazonaws.com"],
            role_statement = role_statement,
        )
    )

    return Ref(cfnrole)

def ami_readonly():
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [Action("ec2",i) for i in ["DescribeImages","DescribeImageAttribute","DescribeTags","DescribeInstances"]],
            Resource = ["*"],
        )

def bucket_permission_read_only(deploy_bucket, source_prefix):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [Action(s,i) for s,i in [("s3","Get*"),("s3","List*")]],
            Resource = [
                Join("",["arn:aws:s3:::",deploy_bucket]),
                Join("",["arn:aws:s3:::",os.path.join(deploy_bucket,source_prefix)]),
                Join("",["arn:aws:s3:::",os.path.join(deploy_bucket,source_prefix,"*")]),
                ],
        )

def bucket_permission(deploy_bucket, deploy_env, deploy_dest = None):
    actions = [
        ("s3","Get*"),
        ("s3","List*"),
        ("s3","Put*"),
        ("s3","CreateMultipartUpload"),
    ]
    #os.path.join adds a trailing slash when "" is used.
    if deploy_dest:
        deploy_path = os.path.join(deploy_bucket,deploy_env,deploy_dest)
    else:
        deploy_path = os.path.join(deploy_bucket,deploy_env)

    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [Action(s,i) for s,i in actions],
            Resource = [
                Join("",["arn:aws:s3:::",deploy_bucket]),
                Join("",["arn:aws:s3:::",deploy_path]),
                Join("",["arn:aws:s3:::",os.path.join(deploy_path,"*")]),
                ],
        )

def ec2_ssmagent():
    actions = [
        ("ssm","DescribeAssociation"),
        ("ssm","GetDocument"),
        ("ssm","ListAssociations"),
        ("ssm","ListInstanceAssociations"),
        ("ssm","UpdateAssociationStatus"),
        ("ssm","UpdateInstanceInformation"),
    ]
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [Action(s,i) for s,i in actions],
            Resource = ["*"]
        )

def notification_permission(deploy_bucket):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [Action(s,i) for s,i in [("s3","GetNotifications"),("s3","ListNotifications"),("s3","PutNotifications")]],
            Resource = [
                Join("",["arn:aws:s3:::",deploy_bucket]),
                ],
        )

def logwatch_permission(log_group):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [
                logs.CreateLogGroup,
                logs.CreateLogStream,
                logs.DescribeLogStreams,
                logs.DescribeLogGroups,
                logs.PutLogEvents
            ],
            Resource = [
                Join("",["arn:aws:logs:*:*:*:", log_group, ":*:*"]),
                ],
        )

def cloudformation_describe(deploy_bucket, aws_region, deploy_env, app_name):
    desc_stack = make_statement(
        actions = [
            awacs.cloudformation.Action("DescribeStack*"),
            awacs.cloudformation.Action("ListExports"),
            awacs.cloudformation.Action("ListImports"),
        ],
        resources = ["*"],
    )
    return desc_stack

def cloudformation_new(deploy_bucket, aws_region, deploy_env, app_name):

    read_bucket = bucket_permission_read_only(
        deploy_bucket = deploy_bucket,
        source_prefix = deploy_env
    )

    new_stack = make_statement(
        actions = [
            awacs.cloudformation.CreateStack,
            awacs.cloudformation.GetTemplate,
            awacs.cloudformation.ValidateTemplate,
            awacs.cloudformation.ListStackResources,
        ],
        condition = awacs.aws.Condition(
            awacs.aws.StringLike(
                "cloudformation:TemplateUrl",
                [
                    "https://s3-{aws_region}.amazonaws.com/{deploy_bucket}/{deploy_env}/*".format(
                        aws_region = aws_region,
                        deploy_bucket = deploy_bucket,
                        deploy_env = deploy_env
                    )
                ]
            )
        ),
        resources = ["arn:aws:cloudformation:"+aws_region+":*:stack/" + app_name + "*"],
    )

    desc_stacks = cloudformation_describe(deploy_bucket, aws_region, deploy_env, app_name)

    return [read_bucket, new_stack, desc_stacks]

def cloudformation_update(deploy_bucket, aws_region, deploy_env, app_name, stack_type):

    update_stack = make_statement(
        actions = [
            awacs.cloudformation.UpdateStack,
        ],
        resources = [
            "arn:aws:cloudformation:{aws_region}:*:stack/{app_name}-{stack_type}*".format(
                aws_region = aws_region,
                app_name   = app_name,
                stack_type = stack_type,
            )
        ],
    )

    desc_stacks = cloudformation_describe(deploy_bucket, aws_region, deploy_env, app_name)

    return [update_stack, desc_stacks]


def lambda_self_logging(app_name):

    #TODO: this should really be: /aws/lambda/app_name-stack_type-lambda_name-*
    self_log_action = make_statement(
        actions = [logs.Action("*")],
        resources = ["arn:aws:logs:*:*:/aws/lambda/" + app_name + "*"],
    )

    return self_log_action

def cloudwatch_metrics():
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [cloudwatch.PutMetricAlarm, cloudwatch.PutMetricData, cloudwatch.ListMetrics],
            Resource = ["*"]
        )

def cloudwatch_del_alarms():
    return awacs.aws.Statement(
        Effect 		= awacs.aws.Allow,
        Action 		= [cloudwatch.DeleteAlarms],
        Resource 	= ["*"],
    )

def ecr_get_auth_token():
    return awacs.aws.Statement(
        Effect   = awacs.aws.Allow,
        Action   = [
                awacs.ecr.GetAuthorizationToken,
                awacs.ecr.BatchGetImage,
                awacs.ecr.GetDownloadUrlForLayer,
            ],
        Resource = [
            "*",
            ],
    )

def control_ec2(aws_region):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [
                awacs.ec2.TerminateInstances,
                awacs.ec2.StartInstances,
                awacs.ec2.StopInstances,
                ],
            Resource = [
                Join("",["arn:aws:ec2:", aws_region, ":*:instance/*"]),
                ],
            #TODO: Would be nice to restrict start/stop/term actions to only instances created by this role
            #But this would require access to tag ec2 instances
            #Condition = awacs.aws.Condition(
                    #awacs.aws.StringEquals({"ec2:ResourceTag/whocreated":"deployserver"}
                    #),
                #)
        )

def run_ec2(aws_region):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [awacs.ec2.RunInstances],
            Resource = [
                Join("",["arn:aws:ec2:", aws_region,":*:instance/*"]),
                Join("",["arn:aws:ec2:", aws_region,":*:image/*"]),
                Join("",["arn:aws:ec2:", aws_region,":*:key-pair/*"]),
                Join("",["arn:aws:ec2:", aws_region,":*:security-group/*"]),
                Join("",["arn:aws:ec2:", aws_region,":*:volume/*"]),
                ],
        )


def networking(name):
    elb = awacs.aws.Statement(
        Effect   = awacs.aws.Allow,
        Action   = [
            awacs.aws.Action("elasticloadbalancing","Describe*"),
            awacs.aws.Action("elasticloadbalancing","Create*"),
        ],
        Resource = [
            Join("",["arn:aws:elasticloadbalancing:", aws_region,":*:loadbalancer/",name]),
        ],
    )

    #subnets
    #security_groups
    #acl
    return [elb, subnets, security_groups, acl]

def ecs_listtasks(name, region = "ap-southeast-2"):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [
                awacs.ecs.ListTasks,
                ],
            Resource = [
                "arn:aws:ecs:"+region+"::"+name+"/*",
                ],
        )

def delegate_role(role_path):
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [awacs.iam.PassRole],
            Resource = [
                Join("",["arn:aws:iam:*:*:",role_path]),
                ],
        )

def get_ecr_image():
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [
                    awacs.ecr.ListImages,
                    awacs.ecr.BatchGetImage,
                    awacs.ecr.GetAuthorizationToken
                ],
            Resource = ["*"],
        )

def join_ecs_cluster():
    return awacs.aws.Statement(
            Effect   = awacs.aws.Allow,
            Action   = [
                    ecs.DeregisterContainerInstance,
                    ecs.DiscoverPollEndpoint,
                    ecs.StartTelemetrySession,
                    ecs.DescribeClusters,
                    ecs.DescribeContainerInstances,
                    ecs.ListClusters,
                    ecs.ListContainerInstances,
                    ecs.ListServices,
                    ecs.ListTaskDefinitions,
                    ecs.ListTaskDefinitionFamilies,
                    ecs.Poll,
                    ecs.RegisterContainerInstance,
                    ecs.RegisterTaskDefinition,
                    ecs.RunTask,
                    ecs.StartTask,
                    ecs.StopTask,
                    ecs.SubmitContainerStateChange,
                    ecs.UpdateContainerAgent,
                    ecs.UpdateService,
                    ecs.SubmitTaskStateChange,
                    ecs.DescribeTasks,
                    ecr.BatchCheckLayerAvailability,
                    ecr.InitiateLayerUpload,
                    ecr.UploadLayerPart,
                    ecr.CompleteLayerUpload,
                    ecr.PutImage,
                    ecr.BatchGetImage,
                    ecr.GetDownloadUrlForLayer,
                    ecr.GetAuthorizationToken,
                ],
            Resource = ["*"],
        )

def app_role(deploy_bucket, deploy_env, log_group):
    role_statement = []
    role_statement.append(bucket_permission(deploy_bucket, deploy_env))
    role_statement.append(logwatch_permission(log_group))
    role_statement.append(cloudwatch_metrics())
    role_statement.append(cloudwatch_del_alarms())
    role_statement.append(ecr_get_auth_token())
    role_statement.append(ami_readonly())
    role_statement.append(ec2_ssmagent())
    return role_statement

def app_profile(template, ops, app_cfn_options, export = True):

    app_name      = ops.app_name
    deploy_bucket = ops.deploy_bucket
    deploy_env    = ops.deploy_env
    log_group     = app_cfn_options.resource_names['log_group']

    role_statement = app_role(deploy_bucket, deploy_env, log_group)

    cfn_instance_profile = ec2_profile(template, app_name, role_statement)

    if export:
        export_ref(
            template,
            export_name = app_cfn_options.resource_names['ec2_iam_profile'],
            value = cfn_instance_profile,
            desc = "IAM Instance Profile that can be used in {app_name} stack".format(app_name=app_name)
        )

    return cfn_instance_profile

def ec2_full():
    ec2role = make_statement(
        actions = [
            awacs.ec2.Action("*"),
        ],
        resources = ["*"],
    )

    return ec2role

def ecs_task(template, app_name, deploy_bucket, deploy_env, log_group, source_path="deploy"):

    role_statement = []
    role_statement.append(bucket_permission(deploy_bucket, deploy_env))
    role_statement.append(bucket_permission(deploy_bucket, source_path))
    role_statement.append(logwatch_permission(log_group))

    cfn_role = ecs_task_role(template, app_name, role_statement)

    return cfn_role

def elb_read():
    elbrole = make_statement(
        actions = [
            awacs.elasticloadbalancing.Action("Describe*"),
        ],
        resources = ["*"],
    )

    return elbrole

def deploy_profile(template, app_name, deploy_bucket, deploy_env, log_groups, ecs_cluster = True):

    role_statement = []
    role_statement.append(bucket_permission(deploy_bucket, deploy_env))
    for log in log_groups:
        role_statement.append(logwatch_permission(log))

    if ecs_cluster:
        role_statement.append(join_ecs_cluster())

    cfn_instance_profile = ec2_profile(template, app_name, role_statement)

    return cfn_instance_profile

def lambda_invoke():
    linvoke = make_statement(
        actions = [
            awacs.awslambda.Action("Get*"),
            awacs.awslambda.Action("Invoke*"),
        ],
        resources = ["*"],
    )

    return linvoke

def pass_role(account_id, app_name):
    prole = make_statement(
        actions = [
            awacs.iam.PassRole,
        ],
        resources = ["arn:aws:iam::{account_id}:role/{app_name}*".format(account_id=account_id, app_name = app_name)],
    )

    return prole
