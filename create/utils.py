import boto3
import hashlib
import io
import os
import zipfile
from botocore.client import Config

def find_files(paths, exclude_suffixes = ['pyc']):
    if type(paths) == str:
        paths = [paths]
    for path in paths:
        if not os.path.isdir(path):
            raise(ValueError("Given path '{}' not a directory".format(path)))
        for o in os.walk(path):
            for p in o[2]:
                if (not check_suffixes(path, exclude_suffixes)):
                    yield os.path.join(o[0],p)


def file_sha(filename):
    with open(filename,'rb') as f:
        sha256 = hashlib.sha256()
        while True:
            d = f.read(65536)
            if not d:
                break
            sha256.update(d)
        return sha256.hexdigest()


def path_sha(path, exclude_suffixes = []):
    #Calc sha of shas in path
    sha256 = hashlib.sha256()
    for f in find_files(path, exclude_suffixes):
        #sha hash based on path and sha of file contents
        sha256.update("".join([f,file_sha(f)]).encode('utf8'))
    return sha256.hexdigest()


def check_suffixes(path, suffixes):
    for s in suffixes:
        if path[-len(s):] == s:
            return True
    return False

def get_s3_client():
    return boto3.client('s3', config=Config(signature_version='s3v4'))

def upload_path_to_zip(s3_bucket, s3_prefix, local_path, dry_run):
    s3 = get_s3_client()

    sha = path_sha(local_path)
    remote_filename = "".join([os.path.basename(local_path),"-",sha,".zip"])
    upload_key = os.path.join(s3_prefix, remote_filename)
    if not dry_run:
        o = s3.list_objects(
            Bucket = s3_bucket,
            Prefix = upload_key
        )
        if not o.get("Contents"):
            print("Uploading local file path to s3bucket {}".format(upload_key))
            upload_body = create_zip(find_files(local_path), local_path)
            s3.put_object(Body = upload_body, Bucket = s3_bucket, Key = upload_key)

    return os.path.join("s3://",s3_bucket, upload_key)


def create_zip(files, root_path):
    mem_obj = io.BytesIO()
    with zipfile.ZipFile(mem_obj, mode='w') as tf:
        for f in files:
            tf.write(f, os.path.relpath(f, start = root_path))
    return mem_obj.getvalue()

def update_dict(dest, src):
    if src is not None:
        for src_key, src_value in src.items():
            if dest.get(src_key):
                raise(ValueError("Parameter '{}' will override existing value".format(src_key)))
            dest[src_key] = src_value
