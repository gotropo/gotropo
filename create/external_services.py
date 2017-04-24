from troposphere.ec2 import SecurityGroupIngress, SecurityGroupEgress
import boto3

def ec2_client(aws_region):
    return boto3.client('ec2', region_name = aws_region)

def get_sec_id(rule, aws_region):
    if rule.get("sec_grp_name") and rule.get("sec_grp"):
        raise(ValueError("Both sec_grp_name and sec_grp given for external service rule {}. Expects either name or id".format(rule)))
    if rule.get("sec_grp_name"):
        ec2 = ec2_client(aws_region)
        descr_grps = ec2.describe_security_groups(
            Filters=[
                {
                    'Name':'tag-key',
                    'Values':['Name']
                },
                {
                    'Name':'tag-value',
                    'Values':[rule.get("sec_grp_name")]
                }
            ])["SecurityGroups"]
        if len(descr_grps) == 1:
            return descr_grps[0]['GroupId']
        elif len(descr_grps) == 0:
            raise(Exception("External security group not found: {}".format(rule.get("sec_grp_name"))))
        else:
            raise(Exception("Multiple groups found for external security group: {}".format(rule.get("sec_grp_name"))))
    else:
        return rule['sec_grp']

def security_group_rules(template, app_name, aws_region, source_grp, services):

    count = 0
    for service_name, service in services.items():
        for rule in service:
            sec_id = get_sec_id(rule, aws_region)
            for port in rule["ports"]:
                #add ingress rules into external service security group
                template.add_resource(
                    SecurityGroupIngress(
                        "".join([app_name, service_name, str(count)]),
                        GroupId = sec_id,
                        SourceSecurityGroupId = source_grp,
                        FromPort = port,
                        ToPort = port,
                        IpProtocol = "tcp"
                    )
                )
                template.add_resource(
                    SecurityGroupIngress(
                        "".join([app_name, "Self", service_name, str(count)]),
                        GroupId = sec_id,
                        SourceSecurityGroupId = sec_id,
                        FromPort = port,
                        ToPort = port,
                        IpProtocol = "tcp"
                    )
                )
                #add egress rules for source group
                template.add_resource(
                    SecurityGroupEgress(
                        "".join([app_name, service_name, "Egress", str(count)]),
                        GroupId = source_grp,
                        DestinationSecurityGroupId = sec_id,
                        FromPort = port,
                        ToPort = port,
                        IpProtocol = "tcp"
                    )
                )
                count += 1
