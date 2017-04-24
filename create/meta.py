from troposphere import Parameter, Ref, Template, Tags

def add_param(template, param_name, default_value, description,cf_type, options = {}):
    cfp = template.add_parameter(Parameter(
        param_name,
        Type=cf_type,
        Default=default_value,
        Description=description,
        **options
    ))
    return cfp

def size_autoscale_params(template):
    Ref(template.add_parameter(Parameter(
        "InstanceType",
        Type="String",
        Description="WebServer EC2 instance type",
        Default="t2.medium",
        AllowedValues=[
            "t2.micro", "t2.small","t2.medium","c4.xlarge","m4.large"
            ],
        ConstraintDescription="must be a valid EC2 instance type.",
    )))
    template.add_parameter(Parameter(
        "MinScaleCapacity",
        Type="Number",
        Default="1",
        Description="Autoscale min capacity",
    ))
    template.add_parameter(Parameter(
        "MaxScaleCapacity",
        Type="Number",
        Default="1",
        Description="Autoscale max capacity",
    ))

def params(template, cf_params_config):

    #Assume any other options in param_options are to be used by cloudformation parameters directly
    cf_param_local_options = ["NoUserdataExport",]

    cf_params = {}
    userdata_exports = []
    for param_name, param in cf_params_config.items():
        default = param['default']
        desc    = param['desc']
        options = param.get('options', None)
        cf_type = param.get('Type',"String")
        if options:
            cf_param_options = { k:v for k,v in sorted(options.items()) if k not in cf_param_local_options }
            cf_params[param_name] = Ref(add_param(template, param_name, default, desc,cf_type,cf_param_options))
        else:
            cf_params[param_name] = Ref(add_param(template, param_name, default, desc,cf_type))
    return cf_params
