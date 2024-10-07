from sonarqube import SonarQubeClient
import sonarqube
import yaml, json
import os
from github import Github
from sys import exit

## creating a Github instance using glcp org personal access token glcp_gh_token
g = Github(os.environ['GITHUB_TOKEN'])

org_name = 'glcp'
org = g.get_organization(org_name)

glcp_teams = [team.slug for team in org.get_teams()]

## Sonarqube Authentication using Hostname and Token (Token is service account glcp-sonarqube user token)
sonar_client = SonarQubeClient(sonarqube_url=os.environ['SONAR_URL'],token=os.environ['SONAR_TOKEN'])

## Loading the details from yaml file
if os.environ['SONAR_ENV'] == 'dev':
    print(f'''ONBOARDING TO SONARQUBE DEV\n''')
    file='../sonar_data/sonar-dev.yaml'
    with open(file, 'r') as file:
        yaml_contents = yaml.safe_load(file)
elif os.environ['SONAR_ENV'] == 'prod':
    print(f'''ONBOARDING TO SONARQUBE PROD\n''')
    file='../sonar_data/sonar.yaml'
    with open(file, 'r') as file:
        yaml_contents = yaml.safe_load(file)
else:
    print("Please provide correct environment variable")
    exit()

## Creating Sonarqube groups wrt GitHub teams
#Listing the existing groups in sonarqube and creating sonar_groups_list with group names
sonar_groups = sonar_client.user_groups.search_user_groups()
sonar_groups_list = [g['name'] for g in sonar_groups['groups']]

#Listing the group names form yaml file
github_groups = yaml_contents['Groups']

formatted_groups = []

for group in github_groups:
    if 'glcp/' in group['name']:
        formatted_groups.append(group['name'].split('glcp/')[1])
    else:
        formatted_groups.append(group['name'])

absent_groups = [ group for group in formatted_groups if group not in glcp_teams ]
default_groups = ['sonar-users', 'sonar-administrators']

#Checking if GitHub team exists
if absent_groups:
    for group_name in absent_groups:
        if group_name not in default_groups:
            raise Exception(f'{group_name} does not exist in glcp_teams')
                   
#Creating a sonarqube GROUP by comparing the groups list from yaml(github_groups) with groups list from sonarqube(sonar_groups_list)
for team in github_groups:
    if team['name'] not in sonar_groups_list:
        sonar_client.user_groups.create_group(name=team['name'], description=team['description'])
        print(f'''\nA new group {team['name']} is created sonarqube\n''') 
    
## Deleting SonarQube group when removed from the yaml file
github_names = [g['name'] for g in github_groups]
groups_to_be_deleted = [c for c in sonar_groups_list if c not in github_names]
for group in groups_to_be_deleted:
    sonar_client.user_groups.delete_group(name=group)
    print(f'''\n{group} group is deleted form sonarqube\n''')

## Onboarding projects to SonarQube
#Creating a new quality gate as per the requirement(The conditions are inherited from Sonar way. The management of conditions are done separately)
quality_gates = sonar_client.qualitygates.get_quality_gates()
quality_gates_list = [s['name'] for s in quality_gates['qualitygates']]
print(f'''\nList of quality gates in Sonarqube\n{quality_gates_list}\n''')
quality_gates = yaml_contents['Projects']

for gate in quality_gates:
    if gate['qualitygate'] not in quality_gates_list:
        sonar_client.qualitygates.copy_quality_gate(name=gate['qualitygate'], sourceName='Sonar way')
        print(f'''\nQualitygate {gate['qualitygate']} is created with Sonar Way conditions\n''')

#Listing the existing projects in soanrqube
sonar_projects = sonar_client.projects.search_projects()
sonar_projects_list = [s['name'] for s in sonar_projects['components']]

#Listing the project names form sonar.yaml file
github_projects = yaml_contents['Projects']

#Creating a sonarqube PROJECTS by comparing the projects list from yaml(github_projects) with projects list from sonarqube(sonar_projects_list) and creating a project token and adding it to the github repository secret for that project.
for project in github_projects:
    if project['name'] not in sonar_projects_list:
        try:
            sonar_client.projects.create_project(project=project['name'], name=project['name'], visibility='private')
        except sonarqube.utils.exceptions.ValidationError as e:
            if 'A similar key already exists' in str(e):
                print(f'''Skipping.....Key already exists for {project['name']}''')
                continue
            raise
        except Exception:
            raise
        print(f'''New project {project['name']} onboarded to Sonarqube''')
        sonar_client.project_branches.rename_project_branch(project=project['name'], name=project['branch'])
        print(f'''Updated default branch of {project['name']} project to {project['branch']}''')
        response = sonar_client.user_tokens.generate_user_token(name=project['name'], type='PROJECT_ANALYSIS_TOKEN', projectKey=project['name'] )
        project_analysis_token = response['token']
        repository = 'glcp/' + project['name']
        repo = g.get_repo(repository)
        repo.create_secret("SONARQUBE_PROJECT_TOKEN", project_analysis_token)
        print(f'''Updating the New Code definition to default branch from Previous Version\n''')
        sonar_client.new_code_periods.set(project=project['name'], branch=project['branch'], type='PREVIOUS_VERSION')
        sonar_client.new_code_periods.set(project=project['name'], type='REFERENCE_BRANCH', value=project['branch'])

## updating the quality gate on an existing project
for project in github_projects:
    try:
        response = sonar_client.qualitygates.get_quality_gate_of_project(project=project['name'])
        quality_gate = response['qualityGate']['name']
        if quality_gate != project['qualitygate']:
            sonar_client.qualitygates.select_quality_gate_for_project(projectKey=project['name'], gateName=project['qualitygate'])
            print(f'''\nQuality Gate for {project['name']} project is updated to {project['qualitygate']}\n''')
    except Exception:
        raise

## Executing the enablement of GitHub Integration for all the lsited projects    
for project in github_projects:
    try:
        response = sonar_client.alm_settings.get_binding(almSetting='GitHub Integration', project=project['name'])
    except sonarqube.utils.exceptions.NotFoundError as x:
        print(f'''Project {project['name']} is not bound to any DevOps Platform''')
        if 'not bound to any DevOps Platform' in str(x):
            print(f'''Configuring DevOps Integration for {project['name']}\n''')
            try:
                sonar_client.alm_settings.set_github_binding(almSetting='GitHub Integration', monorepo='false', project=project['name'], repository='glcp/'+project['name'])
            except Exception:
                raise
            continue
        raise
    except Exception:
        raise
        
## Generating tokens for sonarqube projects for which token are deleted by mistake or never created.
# get all user_tokens from sonarqube and project names to a list
t_sonar_tokens = sonar_client.user_tokens.search_user_tokens(login="glcp-sonarqube")
t_sonar_tokens_list = [g['name'] for g in t_sonar_tokens['userTokens']]

# get all project names from sonarqube api 
t_sonar_projects = sonar_client.projects.search_projects()
t_sonar_projects_list = [g['name'] for g in t_sonar_projects['components']]

# compare both lists and generate token in sonarqube for projects which dont have token
projects_without_token = [c for c in t_sonar_projects_list if c not  in t_sonar_tokens_list]

# generate token for the projects_without_token list
for project in projects_without_token:
    try:
        response = sonar_client.user_tokens.generate_user_token(name=project,type='PROJECT_ANALYSIS_TOKEN', projectKey=project )
        project_analysis_token = response['token']
        repository = 'glcp/' + project
        try:
            repo = g.get_repo(repository)
            if repo:
                repo.create_secret("SONARQUBE_PROJECT_TOKEN", project_analysis_token)
        except:
            pass
    except:
        pass
