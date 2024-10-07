#!/usr/bin/env python3
import requests
import json
import sys
import yaml
import os

api_url = 'https://api.github.com/graphql'
github_token = os.environ['GITHUB_APP_TOKEN']
organisation = 'glcp'
repositories = []
repository_ids = []
access_to_secrets = ['SECRET1', 'SECRET2']

headers = {
    'Authorization': f'Bearer {github_token}',
    'Content-Type': 'application/json'
}
required_status_check_contexts = ["mci-check / secret-scanner / Secret_Scan", "mci-check / malware-scanner"]

try:
    sys.argv[1]
except IndexError:
    sys.exit("workflow-deployment.yaml file expected as input argument")
    
def main():
    """This function process YAML input file and fetches repository names into list"""
    file_path = sys.argv[1]
    with open(file_path, 'r') as file:
        yaml_content = file.read()

    # Parse the YAML content
    parsed_yaml = yaml.safe_load(yaml_content)
    # Fetch repositories names into a list
    repositories = []
    modules = parsed_yaml.get('modules', [])
    for module in modules:
        repositories.extend([repo['name'] for repo in module.get('repositories', [])])
    globals()["repositories"] = repositories
    if bool(repositories):
        create_list_repo_ids(repositories)
    else:
        print("Unable to fetch repository names from input file")

def create_list_repo_ids(repositories):
    """This functions creates list of repository ids where secret access needs to be updated"""
    auth_header = {'Authorization': 'token '+github_token, 'X-GitHub-Api-Version': '2022-11-28', 'Accept': 'application/vnd.github+json'}
    repository_ids = []
    for repo in repositories:
        githubapi = "https://api.github.com/repos/"+organisation+"/"+repo
        repo_response = requests.get(githubapi, headers=auth_header)
        repository_ids.append(repo_response.json()['id'])
    globals()["repository_ids"] = repository_ids
    if bool(repository_ids):
        update_secret_access_to_repo(repository_ids)
    else:
        print("Unable to create list of repository ids")

def update_secret_access_to_repo(repository_ids):
    """This function adds the repositories for to access Organisation secrets"""
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {github_token}',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    for secret in access_to_secrets:
        url = "https://api.github.com/orgs/"+organisation+"/actions/secrets/"+secret+"/repositories"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            response_data = json.loads(response.text)
            existing_repo_ids = [rule ["id"] for rule in response_data["repositories"]]
            repo_ids = list(set(existing_repo_ids + repository_ids))
            data = {
                "selected_repository_ids": repo_ids
            }
        except requests.exceptions.RequestException as e:
            print(f'Error while fetching existing repository names for {secret} secret')
        try:
            response = requests.put(url, headers=headers, json=data)
            response.raise_for_status()
            print(f'Updated access to the {secret} secret for all given repos')
        except requests.exceptions.RequestException as e:
            print(f"Failed to update the secret access for repository. Status code: {response.status_code} {str(e)}")

def check_repo_exist(repository):
    """ This Function checks if given Github Repo exists """
    query = f'''
    query {{
        repository(owner: "{organisation}", name: "{repository}") {{
            id
        }}
    }}
    '''
    try:
        response = requests.post(api_url, json={"query": query}, headers=headers)
        response.raise_for_status()
        repository_id = response.json().get("data", {}).get("repository")['id']
        if repository_id:
            get_default_branch(repository_id, repository)
        else:
            print(f"The repository '{repository}' does not exist.")
            raise ValueError("The repository '{repository}' does not exist.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to query GitHub GraphQL API. Status code: {response.status_code} {str(e)}")
        raise ValueError("The repository '{repository}' does not exist.")

def get_default_branch(repository_id, repository):
    """ This Function gets default branch for given repo """
    query = f'''
    query {{
    repository(owner: "{organisation}", name: "{repository}") {{
        defaultBranchRef {{
        name
        }}
    }}
    }}
    '''
    variables = {
        "owner": organisation,
        "name": repository
    }
    
    try:
        response = requests.post(api_url, headers=headers, json={'query': query, 'variables': variables})
        response.raise_for_status()
        default_branch = response.json()['data']['repository']['defaultBranchRef']['name']
        check_if_branch_protected(repository, repository_id, default_branch)
    except requests.exceptions.RequestException as e:
        print('Failed to retrieve the default branch. Status code:', response.status_code)
        raise ValueError("Failed to retrive default branch for repository {repository} {str(e)}.")

def check_if_branch_protected(repository, repository_id, default_branch):
    """ This function checks if branch protection is already enabled for default branch"""
    query = '''
    query {
    repository(owner: "%s", name: "%s") {
        branchProtectionRules(first: 100) {
        nodes {
            id
            requiredStatusCheckContexts
            pattern
        }
        }
    }
    }
    ''' % (organisation, repository)
    try:
        response = requests.post(api_url, json={"query": query}, headers=headers)
        response.raise_for_status()
        data = response.json().get("data", {}).get("repository", {}).get("branchProtectionRules", {}).get("nodes", [])
        response_data = json.loads(response.text)
        protected_branches = [rule["pattern"] for rule in response_data["data"]["repository"]["branchProtectionRules"]["nodes"]]
        if default_branch not in protected_branches:
            create_branchprotection_rule(repository, repository_id, default_branch)
        else:
            for rule in response_data["data"]["repository"]["branchProtectionRules"]["nodes"]:
                if rule["pattern"] == default_branch:
                    protection_rule_id = rule["id"]
                    protected_status_check_context = rule["requiredStatusCheckContexts"]
                    updated_status_check_context = list(set(protected_status_check_context + required_status_check_contexts))
                    temp_list = ', '.join(f'"{item}"' for item in updated_status_check_context)
                    updated_status_check_context = '['+temp_list+']'
                    update_branchprotection_rule(repository, protection_rule_id, default_branch, updated_status_check_context)       
    except requests.exceptions.RequestException as e:
        print(f"Failed to query GitHub GraphQL API. Status code: {response.text} {str(e)}")
        raise ValueError("Failed to check branch protection rule for {repository}")

def create_branchprotection_rule(repository, repository_id, default_branch):
    """ This function creates the branch protection rule """
    global required_status_check_contexts
    temp_list = ', '.join(f'"{item}"' for item in required_status_check_contexts)
    status_check_contexts = '['+temp_list+']'
    query = f'''
    mutation {{
    createBranchProtectionRule(input: {{
        clientMutationId: "uniqueId",
        repositoryId: "{repository_id}",
        pattern: "{default_branch}",
        requiredStatusCheckContexts: {status_check_contexts},
        requiresStatusChecks: true,
        requiresStrictStatusChecks: true
    }}) {{
        branchProtectionRule {{
        id
        pattern
        requiredStatusCheckContexts
        requiresStatusChecks
        requiresStrictStatusChecks
        }}
    }}
    }}
    '''
    try:
        response = requests.post(api_url, json={"query": query}, headers=headers)
        response.raise_for_status()
        try:
            data = response.json().get("data", {}).get("createBranchProtectionRule", {}).get("branchProtectionRule", {})
        except AttributeError:
            print(f'Failed to create branch protection rule for {repository}. Response: {response.text}')
        if data:
            print(f'Branch protection rule created successfully for {repository} on default branch {default_branch}.')
            print("Required Status Check Contexts:", data["requiredStatusCheckContexts"])

        else:
            print(f'Failed to create branch protection rule for {repository} on default branch {default_branch}.')
    except requests.exceptions.RequestException as e:
        print(f"Failed to query GitHub GraphQL API. Response: {response.text} {str(e)}")

def update_branchprotection_rule(repository, protection_rule_id, default_branch, updated_status_check_context):
    """ This function updates the branch protection rule """
    query = f'''
    mutation {{
    updateBranchProtectionRule(input: {{
        clientMutationId: "uniqueId1",
        branchProtectionRuleId: "{protection_rule_id}"
        pattern: "{default_branch}",
        requiredStatusCheckContexts: {updated_status_check_context},
        requiresStatusChecks: true,
        requiresStrictStatusChecks: true
    }}) {{
        branchProtectionRule {{
        id
        pattern
        requiredStatusCheckContexts
        requiresStatusChecks
        requiresStrictStatusChecks
        }}
    }}
    }}
    '''
    try:
        response = requests.post(api_url, json={"query": query}, headers=headers)
        response.raise_for_status()
        try:
            data = response.json().get("data", {}).get("updateBranchProtectionRule", {}).get("branchProtectionRule", {})
        except AttributeError:
            print(f'Failed to update branch protection rule for {repository}. Response: {response.text}')
        if data:
            print(f'Branch protection rule updated successfully for {repository} on default branch "{default_branch}".')
            print("Required Status Check Contexts updated as: ", data["requiredStatusCheckContexts"])
        else:
            print(f'Failed to updated branch protection rule for {repository} on default branch "{default_branch}".')
    except requests.exceptions.RequestException as e:
        print(f"Failed to query GitHub GraphQL API. Response: {response.text} {str(e)}")

main()

for repo in repositories:
    try:
        check_repo_exist(repo)
    except Exception as e:
        print(f'Error while working on {repo}: {str(e)}')
        continue
