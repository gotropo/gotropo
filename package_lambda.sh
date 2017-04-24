#!/bin/bash -eu

upload_bucket=s3://$1
upload_bucket_pref=$2
upload_bucket_dest=${upload_bucket}/${upload_bucket_pref}

lambda_funcs_dir="${BASH_SOURCE%/*}/create/custom/"
pushd $lambda_funcs_dir

for i in *.py;
do
  func_name=${i%\.py}
  sha=$(sha256sum ${i} | awk '{print $1}')
  zip_filename=${func_name}-${sha}.zip

  {
  aws s3 ls ${upload_bucket_dest}/${zip_filename}
  } || {
    echo "Uploading function to s3"
    zip -q -r ${zip_filename} ${func_name}.py lambda_signals requests
    aws s3 cp ${zip_filename} ${upload_bucket_dest}/${zip_filename}
    rm ${zip_filename}
  }
done
popd
