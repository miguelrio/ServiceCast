import sys
import importlib.util
import importlib.machinery

from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility

# A set of mappings for a system variables to the name of a loaded attribute
mappings = [    ("Utility.alpha", "ALPHA"),
                ("Verbose.level", "VERBOSE_LEVEL"),
                ("Verbose.table", "VERBOSE_TABLE"),
                ("Graph.default_propagation_delay", "GRAPH_DELAY"),
                ("Router.hop_by_hop", "ROUTER_HOP_BY_HOP"),
                ("Router.fib_utility_update_threshold", "ROUTER_FIB_UPT"),
                ("Server.slots", "SERVER_SLOTS"),
                ("Server.change_factor", "SERVER_CF")
            ]

# Import some values from a .py file
# These values become attributes
class Importer(object):

    def __init__(self, namespace, module_name='config'):
        self.namespace = namespace
        self.config_module_name = module_name


    # import a python file
    # using approach as defined in importlib docs
    # and set the module name
    def import_from_path(self, file_path, auto_config=False):
        module = self.import_from_path_as_module(file_path, self.config_module_name)

        if auto_config == True:
            self.configure_system_variables(module)

        return self
        

    # import a python file
    # as defined in importlib docs
    # and set the module name
    def import_from_path_as_module(self, file_path, module_name):
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        self.namespace[module_name] = module

        #print("module = " + str(vars(module)))
        #print("module keys = " + str(vars(module).keys()))

        # patch the module values as attributes of this class
        for name, value in vars(module).items():
            if not name.startswith("_"):
                setattr(self, name, value)
        
        
        return module



    # Configure system variables
    # specific for servicecast
    def configure_system_variables(self, config):
        for system_variable, attr  in mappings:

            # try to update the system variable from an attribute
            self.update(system_variable, attr)
        
    # Update a variable from a named attribute
    def update(self, variable,  name):
        #print("update " + str(variable) + " = " + str(value))

        value = getattr(self, name)
        
        if name in self.__dict__.keys():
            # we have that name

            # split out class name and attribute name
            class_name, attr_name = variable.split(".", 1)

            # get the class
            cls = self.namespace[class_name]

            #print("cls = " + str(cls))

            # set the attribute for that class
            setattr(cls, attr_name, value)

            print(str(variable) + " set to " + str(value), file=sys.stderr)
        else:
            # the name is not it __dict__
            #print("NO variable " + str(variable), file=sys.stderr)
            pass
            

    # Patch up __getattr__ so it return None if a name does not exist
    def __getattr__(self, name):
        if not name in self.__dict__.keys():
            return None
        else:
            # Default behaviour
            return self.__getattribute__(name)            
