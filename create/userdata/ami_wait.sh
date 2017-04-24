#signal build success
SUCCESS=0

cat <<- EOF >>/etc/rc.local
	#Wait for ami on boot if this is tagged with AmiBuild
	#First: check if ami has been created. If so, wait for ami
	#Otherwise: signal build success and then start waiting for ami
	#TODO: add proper logging out to cloudwatch
	exec 3>&1 1>>/var/log/cloud-init-output.log 2>&1
	set -xeu
	instance_id=\$(curl http://169.254.169.254/latest/meta-data/instance-id)
	#TODO: make describe-tags a function
	aws ec2 describe-tags --region ${STACK_REGION} --filter "Name=resource-id,Values=\${INSTANCE_ID}" \\
	  --query "Tags[?Key=='AmiBuild'].Value" | grep "True"
	if [[ \$? -eq 0 ]]
	then
	  echo Waiting for AMI up on boot >> /var/log/cloud-init-output.log
	  ami_filter="Name='tag-key',Values='custom:uuid' Name='tag-value',Values=${ami_uuid}'

	  #If ami does not exist signal that the build is complete.
	  aws ec2 describe-images --region ${STACK_REGION} --filters \${ami_filter} | grep ${ami_uuid}
	  if [[ \$? -eq 1 ]]
	  then
	    echo Signal build is complete >> /var/log/cloud-init-output.log
	    /opt/aws/bin/cfn-signal -e ${SUCCESS} --stack ${STACK_NAME} --region ${STACK_REGION} ${BUILD_WAIT_URL}
	  fi

	  aws ec2 wait image-available --filters \${ami_filter} --region ${STACK_REGION}
	  /opt/aws/bin/cfn-signal -e 0 --stack ${STACK_NAME} --region ${STACK_REGION} ${ami_wait_url}
	fi
EOF
#TODO: For debug, remove
cat /etc/rc.local
reboot
