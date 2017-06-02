from itertools import chain
from troposphere import (
    Template, Output, ImportValue, Export,
    GetAtt, Ref, FindInMap
)
import troposphere as trop
import boto3
from troposphere.cloudformation import WaitCondition, WaitConditionHandle
from create import export_ref, import_ref
import create.network
import create.logs
import create.ec2
import create.build_ami
import create.iam
import create.cloudfront
import create.health_check
import create.external_services
import create.events
import create.prerun
import create.mongo
import create.rds
import create.tcpstacks
from .utils import update_dict

def create_template(app_name, stack_type):
    template = Template()
    template.add_version("2010-09-09")

    template.add_description(
            "{app_name} {stack_type} cloudformation created by troposphere".format(app_name=app_name, stack_type=stack_type)
            )

    return template


def create_network_names(ops):
    app_name = ops.app_name
    net_names = dict(
        #Subnets
        app_subnet_names = ["".join([app_name,"Sn","App",key]) for key,val in sorted(ops.app_networks.items())],
        #Security Groups
        app_sg_name = app_name+"Sg"+"App",
        #Network ACL rules
        app_nacl_name = app_name+"NetAcl"+"App",
    )

    if ops.get("elb_bucket"):
        net_names.update(
            elb_subnet_names = ["".join([app_name,"Sn","Elb",key]) for key,val in sorted(ops.elb_networks.items())],
            elb_sg_name = app_name+"Sg"+"Elb",
            elb_nacl_name = app_name+"NetAcl"+"Elb",
        )

    if ops.get('tcpstacks'):
        net_names['tcpstacks'] = dict()
        for service_name,service_setup in ops.tcpstacks.items():
            join_sn_name = lambda x: "".join([ops.app_name, "Sn", service_name, x])
            stack_subnet_names = [join_sn_name(key) for key in sorted(service_setup['networks'].keys())]

            service_net_names = dict(
                sg_name      = ops.app_name+"Sg"+service_name,
                subnet_names = stack_subnet_names,
                nacl_name    = "".join([ops.app_name, "NetAcl", service_name]),
            )

            if (service_setup['stack_type'] == "rds" ): #TODO: change this to a supported list of types
                service_net_names['rds_subnet_grp_name'] = app_name + "RDSSnGroup"
            net_names['tcpstacks'][service_name] = service_net_names

    if ops.get("elb_bucket"):
        net_names.update(
            elb_subnet_names = ["".join([app_name,"Sn","Elb",key]) for key,val in sorted(ops.elb_networks.items())],
            elb_sg_name = app_name+"Sg"+"Elb",
            elb_nacl_name = app_name+"NetAcl"+"Elb",
        )
    return net_names

def create_resource_names(ops):
    resource_names = dict(
        ec2_iam_profile = "{app_name}Iam".format(app_name = ops.app_name),
        log_group       = "{app_name}Logs".format(app_name = ops.app_name)
    )

    if ops.build_ami:
        resource_names['build_ami_role'] = "{app_name}BuildAmiLambdaRole".format(app_name = ops.app_name)
        resource_names['ec2_amibuild_profile'] = "{app_name}AmiBuildInstanceIamProfile".format(app_name = ops.app_name)

    if ops.cloudwatch_alarm:
        resource_names['cloudwatch_alarm_role'] = "{app_name}CloudwatchAlarmLambdaRole".format(app_name = ops.app_name)

    if ops.get("build_stack_profile"):
        resource_names['build_stack_profile'] = "{app_name}BuildStackProfile".format(app_name = ops.app_name)

    return resource_names

def cfn_options_setup(template, ops):
    cfn_options                = create.config.ConfigOptions()
    cfn_options.network_names  = create_network_names(ops)
    cfn_options.resource_names = create_resource_names(ops)
    cfn_options.resource       = {k:import_ref(v) for k,v in cfn_options.resource_names.items()}
    cfn_options.cf_params      = create.meta.params(template, ops.cf_params)
    cfn_options.log_group      = import_ref(cfn_options.resource_names['log_group'])

    return cfn_options

def resources_stack_template(ops, dry_run):
    template = create_template(ops.app_name, "Resources")
    app_name = ops.app_name
    app_cfn_options = create.config.ConfigOptions()
    app_cfn_options.resource_names = create_resource_names(ops)

    create.logs.log_group(template, ops, app_cfn_options.resource_names['log_group'])

    create.iam.app_profile(template, ops, app_cfn_options)

    if ops.build_ami:
        create.build_ami.build_ami_role(template, ops, app_cfn_options)
        create.build_ami.ec2_amibuild_profile(template, ops, app_cfn_options)

    if ops.cloudwatch_alarm:
        create.health_check.health_check_iam(template, ops, app_cfn_options)

    if ops.get("build_stack_profile"):
        create.iam.build_stack_profile(template, ops, app_cfn_options)

    if ops.get("s3_triggers"):
        create.events.s3triggers(template, ops, app_cfn_options)

    return template

def network_stack_template(ops, dry_run):
    app_name   = ops.app_name
    aws_region = ops.aws_region
    billing_id = ops.billing_id
    deploy_env = ops.deploy_env
    template = create_template(app_name, "Network")
    app_cfn_options = create.config.ConfigOptions()
    app_cfn_options.network_names = create_network_names(ops)
    #Use sets to list unique ports
    public_ports = set([val[0] for key,val in ops.port_map.items()])
    app_ports    = set([val[1] for key,val in ops.port_map.items()])
    app_nets     = [val for key,val in sorted(ops.app_networks.items())]

    if ops.get("elb_bucket"):
       elb_nets     = [val for keys,val in ops.elb_networks.items()]
       #TODO: this can be cleaner with a iterator
       elb_subnet = []
       for count,(az,cidr) in enumerate(sorted(ops.elb_networks.items())):
           net_name = app_cfn_options.network_names['elb_subnet_names'][count]
           subnet   = create.network.subnet(template, ops.vpc_id, net_name, cidr, ops.availability_zones[az], billing_id, deploy_env)
           elb_subnet.append(subnet)
           create.network.routetable(template, ops.vpc_id, "Route"+net_name, subnet, igw_id=ops.igw_id)
           export_ref(template, net_name, value = subnet, desc = "Export for elb subnet")
       elb_custom_rules = [(e[0],e[1],"egress") for e in create.network.combine(app_nets, app_ports)]
       elb_custom_rules.extend(ops.get("custom_elb_rules", []))
       elb_sg = create.network.sec_group(template,
           name         = app_cfn_options.network_names['elb_sg_name'],
           in_networks  = sorted(ops.public_ips),
           in_ports     = public_ports,
           out_ports    = ops.out_ports,
           custom_rules = elb_custom_rules,
           ops          = ops,
       )
       export_ref(template, app_cfn_options.network_names['elb_sg_name'], value = elb_sg, desc = "Export for elb security group")
       elb_app_networks = [net for key,net in chain(ops.elb_networks.items(), ops.app_networks.items())]
       if ops.get("use_cloudfront"):
           elb_nacl_factory = create.network.AclFactory(
               template,
               name         =  "{app_name}ELBDefaultNACL".format(app_name=ops.app_name),
               vpc_id       = ops.vpc_id,
               in_networks  = ["0.0.0.0/0"],
               in_ports     = ["443"],
               out_ports    = ["80","443"],
               out_networks = ["0.0.0.0/0"],
           )
           for count,subnet in enumerate(elb_subnet):
               assoc_name = "ElbAclAssoc"+str(count)
               create.network.assoc_nacl_subnet(template, assoc_name, elb_nacl_factory.nacl, subnet)
       else:
           elb_nacl_factory = create.network.AclFactory(
               template,
               name         = app_cfn_options.network_names['elb_nacl_name'],
               vpc_id       = ops.vpc_id,
               in_networks  = ops.public_ips,
               in_ports     = public_ports,
               out_ports    = ops.out_ports,
               out_networks = elb_app_networks,
           )
           for count,subnet in enumerate(elb_subnet):
               assoc_name = "ElbAclAssoc"+str(count)
               create.network.assoc_nacl_subnet(template, assoc_name, elb_nacl_factory.nacl, subnet)
    else:
       elb_nets = []
       elb_subnet = []
       elb_app_networks = []


    app_subnets = []
    for count,(az,cidr) in enumerate(sorted(ops.app_networks.items())):
        net_name = app_cfn_options.network_names['app_subnet_names'][count]
        subnet   = create.network.subnet(template, ops.vpc_id, net_name, cidr, ops.availability_zones[az], billing_id, deploy_env)
        app_subnets.append(subnet)
        use_nat = ops.get("use_nat")
        use_nat_gw = ops.get("use_nat_gw")
        if use_nat and use_nat_gw:
            raise(ValueError("Both Nat and Nat Gateway can not be turned on"))
        nat_id = None
        if use_nat:
            nat_id = ops.nat_ids[az],
        if use_nat_gw:
            nat_id = ops.nat_gw_ids[az],
        if use_nat and use_nat_gw:
           raise(ValueError,"Both nat and nat_gw are true")

        create.network.routetable(
            template,
            ops.vpc_id,
            "Route"+net_name,
            subnet,
            vpn_id = ops.get("ofc_vpn_id"),
            nat_id = nat_id,
            vpn_route = ops.get("vpn_route"),
            use_nat = ops.get("use_nat"),
            use_nat_gw = ops.get("use_nat_gw")
        )

        export_ref(template, net_name, value = subnet, desc = "Export for app subnet")


    #TODO: fix this
    app_sg = create.network.sec_group(template,
        name         = app_cfn_options.network_names['app_sg_name'],
        in_networks  = sorted(elb_nets),
        in_ports     = app_ports,
        out_ports    = ops.out_ports,
        ssh_hosts    = ops.get("deploy_hosts"),
        custom_rules = ops.get("custom_app_rules"),
        ops          = ops,
    )
    export_ref(template, app_cfn_options.network_names['app_sg_name'], value = app_sg, desc = "Export for app security group")
    app_nacl_factory = create.network.AclFactory(
            template,
            name         = app_cfn_options.network_names['app_nacl_name'],
            vpc_id       = ops.vpc_id,
            in_networks  = elb_nets,
            in_ports     = app_ports,
            out_ports    = ops.out_ports,
            out_networks = elb_app_networks,
            ssh_hosts    = ops.get("deploy_hosts"),
    )

    for count,subnet in enumerate(app_subnets):
        assoc_name = "AppAclAssoc"+str(count)
        create.network.assoc_nacl_subnet(template, assoc_name, app_nacl_factory.nacl, subnet)

    last_rule_number = 1000
    for service,service_setup in ops.get("tcpstacks",{}).items():
        if service_setup['enabled']:
            stack_name =  service
            stack_sg_name = app_cfn_options['network_names']['tcpstacks'][service]['sg_name']
            sg_rules = dict(sec_grp = ImportValue(stack_sg_name), ports = service_setup['ports'])
            sg_key   = "".join([service,"ExtSecGrpPorts"])
            ext_stack = {sg_key: [sg_rules]}
            create.external_services.security_group_rules(template, app_name, aws_region, app_sg, ext_stack)

            stack_nacl_name = app_cfn_options['network_names']['tcpstacks'][service]['nacl_name']
            nacl = ImportValue(stack_nacl_name)

            last_rule_number = create.network.acl_add_networks(template, stack_nacl_name, nacl, app_nets, start_rule=last_rule_number) #TODO: describe nacl to find value for start_rule
            last_rule_number += 10
            tcpstack_networks = [n for az, n in service_setup['networks'].items()]
            create.network.acl_add_networks(template, app_cfn_options.network_names['app_nacl_name']+service, app_nacl_factory.nacl, tcpstack_networks, start_rule=1000)

    if ops.get("external_services"):
        create.external_services.security_group_rules(template, app_name, aws_region, app_sg, ops.external_services)

    return template


def app_stack_template(ops, dry_run):

    template = create_template(ops.app_name, "App")

    app_name = ops.app_name

    if ops.get("app_prerun"):
        create.prerun.call(template, ops.app_prerun, dry_run)


    external_ports = [val[0] for val in ops.port_map.values()]
    internal_ports = [val[1] for val in ops.port_map.values()]

    app_cfn_options = cfn_options_setup(template, ops)

    app_cfn_options.app_ec2_name  = app_name+"App"
    app_cfn_options.app_subnets             = [import_ref(s) for s in app_cfn_options.network_names['app_subnet_names']]
    app_cfn_options.app_sg                  = import_ref(app_cfn_options.network_names['app_sg_name'])
    app_cfn_options.iam_profile             = import_ref(app_cfn_options.resource_names['ec2_iam_profile'])

    app_cfn_options.autoscale_name     = app_name+"Autoscale"
    app_cfn_options.launch_config_name = app_name+"LaunchConfig"

    if ops.get("elb_bucket"):
       app_cfn_options.elb_subnets   = [import_ref(s) for s in app_cfn_options.network_names['elb_subnet_names']]
       app_cfn_options.elb_name      = app_name+"Elb"
       app_cfn_options.elb_sg        = import_ref(app_cfn_options.network_names['elb_sg_name'])
       app_cfn_options.elb = create.ec2.elb(template,
           elb_name        = app_cfn_options.elb_name,
           billing_id      = ops.billing_id,
           elb_subnet      = app_cfn_options.elb_subnets,
           sec_grp         = app_cfn_options.elb_sg,
           ssl_cert        = ops.SSLCert_arn,
           port_map        = ops.port_map,
           health_chk_port = internal_ports[0],
           ops             = ops,
       )
       elb_export = "".join([ops.app_name,"ELB"])
       template.add_output([
           Output(elb_export,
               Description = "CName for created ELB",
               Value       = GetAtt(app_cfn_options.elb_name, "DNSName"),
               Export      = Export(name=elb_export)
           )
       ])
    else:
       app_cfn_options.elb      = None
       app_cfn_options.elb_name = ""

    if ops.get("build_ami"):
        ec2_ami = create.build_ami.build_ami(template, ops, app_cfn_options)
    else:
        ec2_ami = None

    if ops.cloudwatch_alarm:
        create.health_check.health_check(template, ops, app_cfn_options)

    create.ec2.app_autoscale(template, ops, app_cfn_options, ami_image = ec2_ami)

    if ops.get("use_cloudfront"):
        create.cloudfront.add_origin(template, ops, app_cfn_options)
    return template


def tcp_stack_template(ops, stack_name, stack_setup, dry_run):

    stack_creates = dict(
        mongodb = create.mongo.mongo_stack,
        rds     = create.rds.rds_setup,
        ec2     = create.tcpstacks.create_ec2_stack,
        ec2_windows = create.tcpstacks.create_ec2_stack,
    )

    template = create_template(ops.app_name, stack_name)

    app_cfn_options = cfn_options_setup(template, ops)

    if stack_setup.get("prerun"):
        create.prerun.call(template, stack_setup['prerun'], dry_run)

    stack_creates[stack_setup['stack_type']](template, ops, app_cfn_options, stack_name, stack_setup)

    return template


def build_stack_template(ops, dry_run):
    template = create_template(ops.app_name,"Build")

    app_cfn_options = create.config.ConfigOptions()
    app_cfn_options.network_names  = create_network_names(ops)
    app_cfn_options.resource_names = create_resource_names(ops)
    app_cfn_options.resource       = {k:import_ref(v) for k,v in app_cfn_options.resource_names.items()}

    stack_name     = ops.app_name
    deploy_bucket  = ops.deploy_bucket
    deploy_env     = ops.deploy_env
    blank_ami_id   = ops.ami_image
    subnet         = import_ref(app_cfn_options.network_names['app_subnet_names'][0])
    sec_grps       = [import_ref(app_cfn_options.network_names['app_sg_name'])]
    log_group      = app_cfn_options.resource_names['log_group']
    userdata_files = [ops.build_stack_userdata]

    app_cfn_options.cf_params = create.meta.params(template, ops.cf_params)

    userdata_vars = create.ec2.userdata_exports(ops, app_cfn_options)

    if ops.get("build_prerun"):
        create.prerun.call(template, ops.build_prerun, dry_run)
        prerun_mappings = [(prerun_name,prerun_setup["var_export"]) for prerun_name,prerun_setup in ops.build_prerun.items()]
        for prerun_name, var_export in prerun_mappings:
            mapping_name = prerun_name.replace("_","-")
            update_dict(userdata_vars, {var_export:FindInMap("PrerunValues", mapping_name, "ReturnString")})

    build_wait_name = "buildEc2Wait"
    build_ec2_wait_handle = template.add_resource(WaitConditionHandle(build_wait_name))
    userdata_vars.update(dict(
        LOG_GROUP = log_group,
        resource_name = Ref(build_ec2_wait_handle),
    ))


    build_ec2_wait = template.add_resource(
        WaitCondition(
            "buildEc2WaitCondition",
            Handle=Ref(build_ec2_wait_handle),
            Timeout="900",
        )
    )
    ec2_instance = template.add_resource(
        trop.ec2.Instance(
            stack_name+"Build",
            ImageId = blank_ami_id,
            UserData = create.ec2.multipart_userdata(
                bash_files       = userdata_files,
                install_packages = ["docker"],
                sub_values       = userdata_vars,
            ),
            InstanceType = "t2.small",
            SubnetId = subnet,
            SecurityGroupIds = sec_grps,
            IamInstanceProfile = app_cfn_options.resource['build_stack_profile'],
        )
    )
    return template
