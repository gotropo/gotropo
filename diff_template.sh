#!/bin/bash -exu

stack_region=$1
stack_name=$2
stack_config_file=$3
stack_type=$4

old_template=$(aws cloudformation get-template --region ${stack_region} --stack-name ${stack_name} --template-stage 'Original' )
new_template=$(go-tropo deploy --dry-run --stack ${stack_type} ${stack_config_file} )
vimdiff <(echo $old_template | jq -S .TemplateBody) <(echo $new_template|jq -S .)
