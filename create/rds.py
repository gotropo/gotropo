from troposphere import rds
from troposphere import Ref, Tags
from .tcpstacks import sub_stack_network

def rds_setup(template, ops, app_cfn_options, stack_name, stack_setup):

    app_name = ops.app_name

    stack_network_info = sub_stack_network(template, ops, app_cfn_options, stack_name, stack_setup)

    rds_sn_grp_name = app_name + "RDSSnGroup"
    stack_subnets   = stack_network_info['stack_subnets']
    stack_sg        = stack_network_info['stack_sg']

    subnet_ids = [subnet for az,subnet in sorted(stack_subnets.items())]
    db_subnet_grp = Ref(
        template.add_resource(
            rds.DBSubnetGroup(
                rds_sn_grp_name,
                DBSubnetGroupDescription = "RDS for " + ops.app_name,
                SubnetIds = subnet_ids,
            )
        )
    )

    db_name        = "".join([ops.app_name,stack_name])
    db_instance_name = "".join([ops.app_name,stack_name])
    db_username    = stack_setup['db_username']
    db_password    = stack_setup['db_password']
    db_zone        = stack_setup['zone']
    db_storage     = stack_setup['Storage']
    db_class       = stack_setup['dbclass']
    db_engine      = stack_setup['engine']
    db_engine_ver  = stack_setup['engine_ver']

    if len(stack_setup['ports']) > 1:
        raise(ValueError("Only one port supported for rds"))
    db_port        =  str(stack_setup['ports'][0])

    db_license     =  stack_setup['license']
    db_param_grp   =  stack_setup['param_grp']
    db_opition_grp =  stack_setup['option_grp']
    db_backup_win  =  stack_setup['backup_win']
    db_maint_win   =  stack_setup['maint_win']
    db_days        =  stack_setup['backup_days']
    db_vpc         =  ops.vpc_id

    rds_db = template.add_resource(
        rds.DBInstance(
            db_name,
            DBName                     = db_name,
            AvailabilityZone           = db_zone,
            MultiAZ                    = False,
            AllocatedStorage           = db_storage,
            DBInstanceClass            = db_class,
            DBInstanceIdentifier       = db_instance_name,
            Engine                     = db_engine,
            EngineVersion              = db_engine_ver,
            Port                       = db_port,
            LicenseModel               = db_license,
            PubliclyAccessible         = False,
            MasterUsername             = db_username,
            MasterUserPassword         = db_password,
            OptionGroupName            = db_opition_grp,
            Tags                       = Tags(Name = db_name,Env = ops.deploy_env,BillingID = ops.billing_id),
            StorageEncrypted           = False,
            AutoMinorVersionUpgrade    = True,
            PreferredBackupWindow      = rds.validate_backup_window(db_backup_win),
            PreferredMaintenanceWindow = db_maint_win,
            BackupRetentionPeriod      = rds.validate_backup_retention_period(db_days),
            DBSubnetGroupName          = db_subnet_grp,
            VPCSecurityGroups          = [stack_sg],
        )
    )
