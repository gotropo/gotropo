yum install -y awslogs || sleep 10
yum install -y awslogs
yum upgrade -y || sleep 10
yum upgrade -y

#TODO: bootstrap logging. Could be nicer
mkdir -p /var/awslogs/state/
echo -e "[plugins]\ncwlogs = cwlogs\n[default]\nregion = ${STACK_REGION}" > /etc/awslogs/awscli.conf
echo -e "[general]\nstate_file = /var/awslogs/state/agent-state\n[/var/log/cloud-init-output]\nfile = /var/log/cloud-init-output.log\nlog_group_name = ${LOG_GROUP}\nlog_stream_name = ${INSTANCE_ID}/cloud-init-output.log\ndatetime_format = %b %d %H:%M:%S" > /etc/awslogs/awslogs.conf
/etc/init.d/awslogs restart
