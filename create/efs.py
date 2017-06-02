from troposphere import Tags,FindInMap, Ref, Template, Parameter,ImportValue, Ref, Output
from troposphere.efs import FileSystem, MountTarget
from troposphere.ec2 import SecurityGroup, SecurityGroupRule, Instance, Subnet
from create import export_ref, import_ref
from create.network import AclFactory, assoc_nacl_subnet


def efs_setup(template, ops, app_cfn_options, stack_name, stack_setup):

    # Variable Declarations
    vpc_id=ops.get('vpc_id')
    efs_sg = app_cfn_options.network_names['tcpstacks'][stack_name]['sg_name']
    efs_acl = app_cfn_options.network_names['tcpstacks'][stack_name]['nacl_name']

    # Create EFS FIleSystem
    efs_fs=FileSystem(
        title='{}{}'.format(ops.app_name, stack_name),
        FileSystemTags=Tags(Name='{}-{}'.format(ops.app_name, stack_name))
    )
    template.add_resource(efs_fs)

    export_ref(template, '{}{}{}'.format(ops.app_name,stack_name,"Endpoint"), value=Ref(efs_fs), desc="Endpoint for EFS FileSystem")


    # EFS FS Security Groups
    efs_security_group=SecurityGroup(
        title=efs_sg,
        GroupDescription='Allow Access',
        VpcId=vpc_id,
        Tags=Tags(Name=efs_sg)
    )
    template.add_resource(efs_security_group)
    export_ref(template, efs_sg, value=Ref(efs_sg), desc="Export for EFS Security Group")

    # Create Network ACL for EFS Stack
    efs_nacl = AclFactory(
        template,
        name=efs_acl,
        vpc_id=ops.vpc_id,
        in_networks=[val for key, val in sorted(ops.app_networks.items())],
        in_ports=stack_setup['ports'],
        out_ports=ops.out_ports,
        out_networks=[val for key, val in sorted(ops.app_networks.items())],
        ssh_hosts=ops.get("deploy_hosts"),
    )
    export_ref(
        template,
        export_name=efs_acl,
        value=Ref(efs_acl),
        desc="{}{} stack".format("NetACL for", stack_name)
    )

    # Create Subnets for Mount Targets
    for k, v in ops['tcpstacks']['EFS']['networks'].items():
        efs_subnet=Subnet(
            title='{}{}{}{}'.format(ops.app_name, stack_name, "MountTargetSubnet", k.split("-")[-1]),
            AvailabilityZone=k,
            CidrBlock=v,
            VpcId=vpc_id,
            Tags=Tags(Name='{}-{}-{}-{}'.format(ops.app_name, stack_name, "MountTargetSubnet", k.split("-")[-1]))
        )
        template.add_resource(efs_subnet)

        assoc_name = '{}{}{}'.format(stack_name,"AclAssoc",k.split("-")[-1])
        assoc_nacl_subnet(template, assoc_name, Ref(efs_acl), Ref(efs_subnet))

        efs_mount_target=MountTarget(
            title='{}{}{}'.format(ops.app_name, "EFSMountTarget", k.split("-")[-1]),
            FileSystemId=Ref(efs_fs),
            SecurityGroups=[Ref(efs_security_group)],
            SubnetId=Ref(efs_subnet)
        )
        template.add_resource(efs_mount_target)
