from sonarqube import SonarQubeClient
import sonarqube
import yaml
import os
from sys import exit

## Sonarqube Authentication using Hostname and Token (Token is service account glcp-sonarqube user token)
sonar_client = SonarQubeClient(sonarqube_url=os.environ['SONAR_URL'],token=os.environ['SONAR_TOKEN'])

# This will read sonar-repos.yaml and check for missing project from SonarQube Analysis
with open('sonar-repos.yml', 'r') as sonar:
    projects_in_yaml = yaml.safe_load(sonar)

def check_project_analysis_with_branch(name, branch_name):
    '''This function checks for the Project where analysis
    not performed on the given branch in yaml file'''
    branches = sonar_client.project_branches.search_project_branches(project=name)
    branches = branches.get('branches', [])
    branch_names = [branch['name'] for branch in branches]
    if branch_name not in branch_names:
        return {name: branch_name}
    for branch in branches:
        if branch['name'] == branch_name and branch.get('isMain', False) and branch.get('excludedFromPurge', False) and 'analysisDate' not in branch:
            return {name: branch_name}

run_analysis_projects = []
# Iterate through Projects for repositories
for module in projects_in_yaml.get('Projects', []):
    name = module.get('name')
    branch = module.get('branch')
    func_response = check_project_analysis_with_branch(name, branch)
    if func_response is not None:
        run_analysis_projects.append(func_response)

script_output = '[' + ', '.join([f'\\"{item}\\"' for item in run_analysis_projects]) + ']'
print(run_analysis_projects)
