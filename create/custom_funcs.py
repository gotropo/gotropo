from troposphere import awslambda
from troposphere import GetAtt, Ref
from . import iam
from .utils import file_sha, find_files, create_zip, get_s3_client
from itertools import repeat
import boto3
import os

def remote_filename(local_file):
    sha = file_sha(local_file)
    filename = os.path.basename(local_file)
    return "".join([filename, "-", sha])


def upload_lambda_code(s3_bucket, s3_prefix, local_file, sha, lib_files = []):
    s3 = get_s3_client()

    local_path = os.path.dirname(os.path.abspath(local_file))

    files = [local_file]
    files.extend(lib_files)
    upload_body = create_zip(files, local_path)

    upload_key = os.path.join(s3_prefix, remote_filename(local_file))
    s3.put_object(Body = upload_body, Bucket = s3_bucket, Key = upload_key)

def check_lambda_code(s3_bucket, s3_prefix, lambda_file, lib_files = []):
    s3 = get_s3_client()

    sha = file_sha(lambda_file)
    remote_file = remote_filename(lambda_file)
    prefix = os.path.join(s3_prefix, remote_file)
    o = s3.list_objects(
        Bucket = s3_bucket,
        Prefix = prefix
    )
    if not o.get("Contents"):
        print("Uploading custom fuction code to s3bucket {prefix}".format(prefix=prefix))
        upload_lambda_code(s3_bucket, s3_prefix, lambda_file, sha, lib_files)

def check_custom_func(deploy_bucket, deploy_env, custom_func_file):
    import sys
    import os

    custom_func_dir = "custom"
    required_libs = ["lambda_signals"]

    module_path    = os.path.dirname(os.path.abspath(__file__))
    local_path     = os.path.join(module_path, custom_func_dir)


    local_filepath = "".join([local_path, "/", custom_func_file, ".py"]) #TODO: fix using /
    paths = [os.path.join(l,k) for l,k in zip(repeat(local_path), required_libs)]
    lib_files = find_files(paths)
    check_lambda_code(deploy_bucket, custom_resource_s3prefix(deploy_env), local_filepath, lib_files = lib_files)

def s3_invoke_permissions(template, name, bucket, lambda_ref):
    invoke_perm = template.add_resource(
        awslambda.Permission(
            name,
            FunctionName  = GetAtt(lambda_ref, "Arn"),
            Action        = "lambda:InvokeFunction",
            Principal     = "s3.amazonaws.com",
            SourceAccount = Ref("AWS::AccountId"),
            SourceArn     = "arn:aws:s3:::"+bucket,
        )
    )
    return Ref(invoke_perm)


def lambda_function(template,
        name,
        deploy_bucket,
        s3_prefix,
        local_file,
        iam_role,
        env_vars = None,
        handler  = None,
    ):
    sha         = file_sha(local_file)
    remote_file = remote_filename(local_file)

    filename = os.path.basename(local_file)
    if filename[-3:] != '.py':
        raise(ValueError, "Unknown filetype for lambda function")

    if not handler:
        handler = str(filename[0:-3])+".handler"

    if not env_vars:
        env = awslambda.Environment(Variables=dict())
    else:
        env = awslambda.Environment(Variables=env_vars)

    return template.add_resource(
        awslambda.Function(
            name,
            Code = awslambda.Code(
                S3Bucket = deploy_bucket,
                S3Key    = s3_prefix + "/" + remote_file,
            ),
            Environment = env,
            Handler = handler,
            Timeout = "120",
            Role = iam_role,
            Runtime = "python2.7",
        )
    )

def custom_resource_s3prefix(deploy_env):
    return deploy_env+"/custom_resources"

def custom_resource(template,
        name,
        deploy_bucket,
        deploy_env,
        lambda_file,
        iam_role,
    ):

    module_path = os.path.dirname(os.path.abspath(__file__))
    local_path  = os.path.join(module_path, "custom/")
    filename    = "{lambda_file}.py".format(lambda_file = lambda_file)
    local_file  = os.path.join(local_path, filename)

    return lambda_function(
        template = template,
        name     = name,
        deploy_bucket = deploy_bucket,
        s3_prefix  = custom_resource_s3prefix(deploy_env),
        local_file = local_file,
        iam_role   = iam_role,
    )

def lambda_iam(template, name, action_statement):
    t = iam.make_assume_role(name, ["lambda.amazonaws.com"], action_statement)
    return template.add_resource(t)
