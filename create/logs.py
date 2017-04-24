from troposphere import logs
from troposphere import Ref
from create import export_ref, import_ref

def log_group(template, ops, log_group_name, retention_days = 5, export = True):
    app_name = ops.app_name

    log_group = Ref(template.add_resource(
        logs.LogGroup(
            log_group_name,
            LogGroupName = log_group_name,
            RetentionInDays = retention_days
        )
    ))

    if export:
        export_ref(
            template,
            export_name = log_group_name,
            value = log_group,
            desc = "Log group used by {app_name} stack".format(app_name=app_name)
        )

    return log_group

