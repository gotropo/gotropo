from troposphere import Export
import importlib

supported_keys = dict(
    var_export = "Name of exported value that will hold return string from given function",
    function   = "Function to call, expects string return value",
    function_args = "Arguments as key=value pairs for function call"
)

def call(template, prerun_items, dry_run):
    prerun_values = dict()
    for k,v in prerun_items.items():
        item_value = run_item(v, dry_run)
        prerun_values[k.replace("_","-")] = dict(ReturnString = item_value)
    template.add_mapping("PrerunValues", prerun_values)

def check_keys(item_setup):
    for k in item_setup.keys():
        if not supported_keys.get(k):
            raise(ValueError("Config key '{}' not supported for prerun setup".format(k)))

def run_item(item_setup, dry_run):
    check_keys(item_setup)
    func_str = item_setup['function'].split(".")
    lib = importlib.import_module(".".join(func_str[:-1]))
    func = getattr(lib, func_str[-1])
    return func(dry_run = dry_run, **item_setup['function_args'])
