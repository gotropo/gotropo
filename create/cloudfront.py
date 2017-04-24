from troposphere import GetAtt, Join, Output
from troposphere import Parameter, Ref, Template, Retain
from troposphere.cloudfront import Distribution, DistributionConfig, CacheBehavior
from troposphere.cloudfront import Origin, DefaultCacheBehavior, ViewerCertificate
from troposphere.cloudfront import ForwardedValues, CustomOrigin, Logging, S3Origin
import boto3

def find_web_acl(wacl_name, web_acl_name):
    wa = boto3.client("waf")

    def get_acl(name, wacl_list):
        for w in wacls:
            if w['Name'] == name:
                return w['WebACLId']
        return None

    r = wa.list_web_acls()
    wacls = r['WebACLs']
    found_wa = get_acl(wacl_name, wacls)
    if found_wa:
        return found_wa
    while r.get('NextMarker'):
        r = wa.list_web_acls(NextMarker = r.get('NextMarker'))
        wacls = r['WebACLs']
        found_wa = get_acl(wacl_name, wacls)
        if found_wa:
            return found_wa
    raise(RuntimeError("No Web acl found with name {}".format(wacl_name)))

def cache_behavior(ops,app_cfn_options):
    viewer_policy = "redirect-to-https"
    cloudfront_cache_behavior = ops.cloudfront_cache_behavior
    if cloudfront_cache_behavior:
      for key,val in sorted(cloudfront_cache_behavior.items()):
        target_origin_id = key
        for path in sorted(val):
            path_pattern  = path
            cachebehavior = CacheBehavior( TargetOriginId       = target_origin_id,
                                           ForwardedValues      = ForwardedValues(QueryString=False),
                                           ViewerProtocolPolicy = viewer_policy,
                                           PathPattern          = path_pattern
                            )
            yield cachebehavior

def add_origin(template, ops, app_cfn_options):
    origin_domain_name = ops.cloudfront_elb_url
    origin_domain_id = ops.app_name
    aws_region = ops.aws_region

    if ops.get('webacl_name'):
        webacl_id = find_web_acl(ops.webacl_name, aws_region)
    else:
        webacl_id   = ops.webacl_id
    default_ttl = ops.get('cloudfront_default_ttl', 7200) #2 hour or config value

    allowed_methods = [ "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT" ]

    customOrigin= CustomOrigin( HTTPPort=80,
                                HTTPSPort=443,
                                OriginProtocolPolicy="https-only",
                                OriginSSLProtocols=["TLSv1.2"]
                  )
    default_origin = Origin ( Id                 = origin_domain_id,
                              DomainName         = origin_domain_name,
                              CustomOriginConfig = customOrigin
                     )
    origins=[]
    origins.append(default_origin)
    if ops.cloudfront_s3_origins:
      for key,val in sorted(ops.cloudfront_s3_origins.items()):
        s3_origin_id = key
        domain_name  = val[0]
        path         = val[1]
        s3_origin    = Origin ( Id            = s3_origin_id,
                           DomainName         = domain_name ,
                           OriginPath         = path ,
                           S3OriginConfig     = S3Origin(  
                                               OriginAccessIdentity = ops.cloudfront_s3_origins_access_identity)
                        )
        origins.append(s3_origin)

    defaultcachebehavior = DefaultCacheBehavior( TargetOriginId       = origin_domain_id,
                         ForwardedValues      = ForwardedValues( Headers=["*"], QueryString=True),
                         DefaultTTL           = default_ttl,
                         AllowedMethods       = allowed_methods,
                         ViewerProtocolPolicy = "redirect-to-https" )

    get_cache_behavior = [ c for c in cache_behavior(ops,app_cfn_options)]

    logging = Logging( Bucket = ops.cloudfront_log_bucket,Prefix = ops.app_name )
    if ops.get("cloudfront_acm_ssl_cert"):
        ssl_cert = ViewerCertificate( AcmCertificateArn = ops.cloudfront_acm_ssl_cert,
                      SslSupportMethod       = "sni-only",
                      MinimumProtocolVersion = "TLSv1")
    else:
        ssl_cert = ViewerCertificate( IamCertificateId       = ops.cloudfront_ssl_cert,
                      SslSupportMethod       = "sni-only",
                      MinimumProtocolVersion = "TLSv1")
    distributionconfig = DistributionConfig( Origins              = origins,
                         DefaultCacheBehavior = defaultcachebehavior,
                         CacheBehaviors       = get_cache_behavior,
                         Enabled          = True,
                         HttpVersion      = 'http2',
                         Logging          = logging,
                         ViewerCertificate= ssl_cert,
                         Comment          = ops.app_name+"-"+ops.aws_region,
                         WebACLId         = webacl_id,
                         Aliases          = ops.cloudfront_aliases)
    dsb = Distribution( "".join([ops.app_name,"Distribution"]),
                   DistributionConfig=distributionconfig, DeletionPolicy=Retain
          )
    distribution = template.add_resource(dsb)
    template.add_output([ Output("DistributionId", Value=Ref(distribution)),
                          Output("DistributionName",Value=origin_domain_name)])
    return  template
