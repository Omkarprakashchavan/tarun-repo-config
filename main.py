import os
import sys
import yaml
import json
import importlib.util


def main():
    if not 'GITHUB_APP_TOKEN' in os.environ:
        print(f'ERROR: Env var "GITHUB_APP_TOKEN" must to be set.')
        sys.exit(1)
    
    filename='workflow-deployment.yaml'
    with open(filename, "r") as yaml_file:
        data = yaml.safe_load(yaml_file)
    modules=data['modules']
    print(f'workflow deployment config:\n{yaml.dump(modules, default_flow_style=False)}')

    for i in modules:
        module_name=i.get('name')
        module_description=i.get('description')
        repositories=i.get('repositories', [])
        module=import_module(module_name)
        module.main(module_name=module_name,
                    module_description=module_description,
                    repositories=repositories)

#This function will load the  specified module dynamically from productModules folder.
def import_module(the_module_name):
    module_dir = 'modules'
    spec = importlib.util.spec_from_file_location(
              the_module_name, 
              f'''{module_dir}/{the_module_name}.py''')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main()
