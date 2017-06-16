import troposphere.ec2
from troposphere import Parameter, Ref, Template, Tags


from itertools import repeat

def combine(networks, ports):
    #return list of all combinations of (network, port)
    return_list = []
    for port in sorted(ports):
        for net_port in zip(networks, repeat(port)):
            return_list.append(net_port)
    return return_list

def subnet(template, vpc_id, name, cidr, az, billing_id, deploy_env):
    sn = template.add_resource(
        troposphere.ec2.Subnet(
            name,
            CidrBlock=cidr,
            VpcId=vpc_id,
            AvailabilityZone=az,
            Tags = Tags(
                Name = name,
                BillingID = billing_id,
                Env = deploy_env
            ),
          )
        )
    return Ref(sn)

def routetable(template, vpc_id, name, subnet, nat_id = None, igw_id = None,
        vpn_id = None, vpn_route = None, use_nat = True, use_nat_gw = False):
    """Create route table for given subnet. Requres either a NAT host, nat_id, or an Internet
    Gateway, igw_id. VPN connection optional"""

    r = template.add_resource(
        troposphere.ec2.RouteTable(
            name,
            VpcId=vpc_id,
        )
    )
    if igw_id:
        route1 = template.add_resource(
            troposphere.ec2.Route(
                name+'route1',
                GatewayId = igw_id,
                DestinationCidrBlock = '0.0.0.0/0',
                RouteTableId = Ref(r),
            )
        )
    else:
        if use_nat:
            if not nat_id:
                raise ValueError("No NAT given and use_nat is true")
            route1 = template.add_resource(
                troposphere.ec2.Route(
                    name+'route1',
                    RouteTableId = Ref(r),
                    DestinationCidrBlock = '0.0.0.0/0',
                    InstanceId = nat_id,
                )
            )
        if use_nat_gw:
            if not nat_id:
                raise ValueError("No NAT given and use_nat is true")
            route1 = template.add_resource(
                troposphere.ec2.Route(
                    name+'route1',
                    RouteTableId = Ref(r),
                    DestinationCidrBlock = '0.0.0.0/0',
                    NatGatewayId = nat_id,
                )
            )
    if vpn_id:
        if not vpn_route:
            raise ValueError("Office VPN Id given without vpn route")
        if type(vpn_route) is str:
            route2 = template.add_resource(
                troposphere.ec2.Route(
                    name+'route2',
                    GatewayId = vpn_id,
                    DestinationCidrBlock = vpn_route,
                    RouteTableId = Ref(r),
                )
            )
        else:
            for count,vpn_r in enumerate(vpn_route):
                template.add_resource(
                    troposphere.ec2.Route(
                        name+'vpnroute'+str(count),
                        GatewayId = vpn_id,
                        DestinationCidrBlock = vpn_r,
                        RouteTableId = Ref(r),
                    )
                )
    ra = template.add_resource(
        troposphere.ec2.SubnetRouteTableAssociation(
            name+"assoc",
            SubnetId=subnet,
            RouteTableId=Ref(r),
        )
    )

def sg_rule(net, port):
    if isinstance(port, int):
        port_num = port
        proto = "tcp"
    else:
        if "/" in port:
            port_num, proto = port.split('/')
        else: #TODO: this shouldn't be here twice
            port_num = port
            proto = "tcp"
    if net[0:2] == "sg":
        sg_r = troposphere.ec2.SecurityGroupRule(
            IpProtocol = proto,
            FromPort   = port_num,
            ToPort     = port_num,
            SourceSecurityGroupId = net
        )
    else:
        sg_r = troposphere.ec2.SecurityGroupRule(
            IpProtocol = proto,
            FromPort   = port_num,
            ToPort     = port_num,
            CidrIp     = net
        )
    return sg_r

def sec_group(template, name, in_networks, in_ports, out_ports, ops, custom_rules = None, ssh_hosts = None):
    vpc_id      = ops.vpc_id
    billing_id  = ops.billing_id
    deploy_env  = ops.deploy_env

    default_out_ports = ['80','443']

    ingress_rules = [sg_rule(net, port) for (net,port) in combine(in_networks, in_ports)]
    if ssh_hosts:
        for dhost in sorted(ssh_hosts):
            ingress_rules.append(sg_rule(dhost, 22))
    egress_rules = [sg_rule('0.0.0.0/0', out_port) for out_port in sorted(out_ports)]

    for dp in default_out_ports:
        if dp not in out_ports:
            egress_rules.append(sg_rule('0.0.0.0/0', dp))

    #TODO: fix this logic
    if custom_rules:
        for cr in custom_rules:
            if len(cr) < 4:
                custom_port = cr[1]
            else:
                custom_port = str(cr[1])+"/"+cr[3]
            if cr[2] == "egress":
                egress_rules.append(sg_rule(net=cr[0],port=custom_port))
            else:
                ingress_rules.append(sg_rule(net=cr[0],port=custom_port))


    sg = template.add_resource(
        troposphere.ec2.SecurityGroup(
            name,
            GroupDescription     = "Cloudformation created security group for " + name,
            SecurityGroupIngress = ingress_rules,
            SecurityGroupEgress  = egress_rules,
            VpcId                = vpc_id,
            Tags = Tags(
                Name = name,
                BillingID = billing_id,
                Env = deploy_env
                )
            )
        )
    return Ref(sg)

def assoc_nacl_subnet(template, name, nacl, subnet):
    return template.add_resource(
        troposphere.ec2.SubnetNetworkAclAssociation(
            name,
            SubnetId=subnet,
            NetworkAclId=nacl,
    ))

def nacl(template, name, vpc_id):
    nacl = template.add_resource(
        troposphere.ec2.NetworkAcl(
            name,
            VpcId = vpc_id,
            Tags = Tags(
                Name = name
            )
        )
    )
    return Ref(nacl)

def acl_add_networks(template, name, nacl, networks, start_rule = 100):
    for count, netw in enumerate(networks):
        rule_number = start_rule + count*10
        for rulename in ['InRule','OutRule']:
            egress = dict(InRule = False, OutRule = True)
            template.add_resource(
                troposphere.ec2.NetworkAclEntry(
                    name+rulename+str(rule_number),
                    NetworkAclId = nacl,
                    RuleNumber   = rule_number,
                    Protocol     = '-1', #TODO config for protocol
                    CidrBlock    = netw,
                    Egress       = egress[rulename],
                    RuleAction   = "Allow"
                )
            )
    return start_rule + count*10

#TODO doesn't seem the best to have this class add to CF template directly, consider alternatives
class AclFactory(object):
    """ Class used to make creating network ACL and rules in troposphere """
    def __init__(self, template, name, vpc_id, in_networks, in_ports, out_ports, out_networks, ssh_hosts = None):
        self.template       = template
        self.name           = name
        self.vpc_id         = vpc_id
        self.in_ports       = in_ports
        self.in_networks    = in_networks
        self.out_networks   = out_networks
        self.in_rule_count  = 0
        self.out_rule_count = 0

        add_nacl_rule = self.add_nacl_rule

        self.create_nacl()

        if ssh_hosts:
            for dhost in ssh_hosts:
               add_nacl_rule(dhost, 22)
        for out_port in out_ports:
            add_nacl_rule('0.0.0.0/0', out_port, egress = 'true')


        for (net, port) in sorted(combine(in_networks, in_ports)):
            add_nacl_rule(net, port)
        self.create_ephemeral_rules()

    def create_nacl(self):
        template = self.template
        name = self.name
        nacl = template.add_resource(
            troposphere.ec2.NetworkAcl(
                self.name,
                VpcId = self.vpc_id,
                Tags = Tags(
                    Name = self.name
                )
            )
        )
        self.nacl = Ref(nacl)

        rule_number = 50
        rulename = 'InRule'
        rule_number = rule_number + 10
        template.add_resource(
           troposphere.ec2.NetworkAclEntry(
                name+rulename+str(rule_number),
                NetworkAclId = Ref(nacl),
                RuleNumber   = rule_number,
                Protocol     = '6',
                PortRange    = troposphere.ec2.PortRange(From=1024, To=65535),
                CidrBlock    = '0.0.0.0/0',
                Egress       = False,
                RuleAction   = "Allow"
            )
        )
        rulename = 'OutRule'
        default_out_ports = [80, 443]
        for port in default_out_ports:
            rule_number = rule_number + 10
            template.add_resource(
                troposphere.ec2.NetworkAclEntry(
                    name+rulename+str(rule_number),
                    NetworkAclId = Ref(nacl),
                    RuleNumber   = rule_number,
                    Protocol     = '6',
                    PortRange    = troposphere.ec2.PortRange(From=port, To=port),
                    CidrBlock    = '0.0.0.0/0',
                    Egress       = True,
                    RuleAction   = "Allow"
                )
            )


    def add_nacl_rule(self, network, port, to_port=None, egress='false'):
        if egress == 'false':
            rule_number = 100 + self.in_rule_count*10
            nacl_name = self.name+"InRule"+str(rule_number)
            self.in_rule_count += 1
        else:
            rule_number = 100 + self.out_rule_count*10
            nacl_name = self.name+"OutRule"+str(rule_number)
            self.out_rule_count += 1
        if to_port is None:
            to_port = port
        self.template.add_resource(
            troposphere.ec2.NetworkAclEntry(
                nacl_name,
                NetworkAclId = self.nacl,
                RuleNumber   = rule_number,
                Protocol     = '6', #TODO config for protocol
                CidrBlock    = network,
                PortRange    = troposphere.ec2.PortRange(From=port, To=to_port),
                Egress       = egress,
                RuleAction   = "Allow"
            )
        )

    def create_ephemeral_rules(self):
        """ Create rules for all unique networks to
        reply to traffic for all networks
        """
        # This seems too open but required for internet access
        self.add_nacl_rule('0.0.0.0/0', 1024, to_port=65535, egress='false')
        self.add_nacl_rule('0.0.0.0/0', 1024, to_port=65535, egress='true')
        #Would be good to lock down to known networks
        #for net in sorted(self.unique_networks):
            #add rule (net)
