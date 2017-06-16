def add_ami(template, ami):
    template.add_mapping("RegionMap", {
        #Add other base AMI images here
        #"ap-southeast-2": {"AMI": "ami-dc361ebf"}, #AWS LINUX
        "ap-southeast-2": {"AMI": ami["ap-southeast-2"]}, #Sydney
        "eu-west-1": {"AMI": ami["eu-west-1"]}, #Dublin
        "eu-west-2": {"AMI": ami["eu-west-2"]},  # London
        "eu-central-1": {"AMI": ami["eu-central-1"]}, #Frankfurt
        "ap-souteast-1": {"AMI": ami["ap-souteast-1"]}, #Singapore

    })
