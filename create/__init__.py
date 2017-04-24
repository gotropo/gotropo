from troposphere import Output, Export, ImportValue
def export_ref(template, export_name, value, desc):
    template.add_output([
        Output(export_name,
            Description = desc,
            Value       = value,
            Export      = Export(name=export_name)
        )
    ])

def import_ref(import_name):
    return ImportValue(import_name)
