import sys
import importlib
import yaml
from itertools import chain
from . import meta
from . import yaml_load


def load_yml_file(config_file):
    with open(config_file, 'r') as f:
        doc = yaml_load.ordered_load(f, yaml.SafeLoader)
    return doc


class ConfigOptions(dict):
    def __init__(self, config = None):
        if type(config) == str:
            self.load_file(config)
        elif type(config) == dict:
            self.load_dict(config)
        else:
            self.config_namespace = {}

    def load_file(self, config_file):
        config_mod = config_file[:-3].replace("/",".")
        try:
            self.update(load_yml_file(config_file))
        except IOError as e:
            print(" ".join(["Error loading config file:", config_file]))
            sys.exit(1)
        except:
            print("Error:", sys.exc_info()[0])
            raise

    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            raise AttributeError("No such attribute: " + name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        if name in self:
            del self[name]
        else:
            raise AttributeError("No such attribute: " + name)


    def load_dict(self, config):
        self.config_namespace = config

def parse(config_file):

    ops = ConfigOptions(config_file)


    return ops
