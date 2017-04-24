from troposphere import Ref
from troposphere import GetAtt
from troposphere import route53
from troposphere import Output
from troposphere import Tags
from . import sns

def record_set(name, target, subdomain, zone, record_type="A"):
    ip = GetAtt(target, "PrivateIp")
    rec_set = route53.RecordSetType(
        name,
        Type = record_type,
        Name = subdomain,
        TTL  = 300,
        HostedZoneName = zone,
        ResourceRecords = [ip]
    )
    return rec_set

def create_record_set(template, name, target, subdomain, zone):
    rec_set = template.add_resource(record_set(
        name,
        target,
        subdomain,
        zone
    ))
    return Ref(rec_set)



def health_check(template, name, fqdn, location="/", port=443, failure_thres = 2,
        chk_type = "HTTPS", request_interval = 10):
    health_check = template.add_resource(route53.HealthCheck(
        name,
        HealthCheckConfig = route53.HealthCheckConfiguration(
            FailureThreshold = failure_thres,
            FullyQualifiedDomainName = fqdn,
            ResourcePath = location,
            Port = port,
            RequestInterval = request_interval,
            Type = chk_type,
        ),
        HealthCheckTags = Tags(Name=name),
    ))
    return health_check
