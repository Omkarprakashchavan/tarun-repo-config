import os
import sys
import yaml
import json
# Import hashlib library (md5 method is part of it)
import hashlib
from typing import Dict, List, Tuple
sys.path.append(f'{os.path.dirname(__file__)}/..')
import utils.myutils as mu
from datetime import datetime
from utils.github_apis import GitHubAPIs
import csv
import traceback
from datetime import datetime
logger = None
topdir = os.path.dirname(os.path.abspath(sys.argv[0]))
logdir = f'{topdir}/logdir'

# pull_request_token=os.environ.get("GIT_TOKEN")
def main(repo_exclude_list,module_description, module_name):
    if not 'ORG_NAME' in os.environ:
        org_name='glcp'
    else:
        org_name=os.environ['ORG_NAME']
        
    token = os.environ.get("GIT_HUB_TOKEN")
    mu.mkdir_p(logdir)
    global logger
    ## Change values accordingly in get_logger()
    logger = mu.get_logger('pull-request-template', f'{logdir}/pull-request-template.log', level='debug', output_to_console=True)
    gh_obj = GitHubAPIs(org_name='glcp', token=token, logger=logger)
    final_repo_list=[]
    print(f'Repo names that are excluded to enforce pull request template\n',repo_exclude_list)
    counter : int = 1
    repos : List[str] = gh_obj.get_repo_names_in_org()
    # repos=['sridhar-py','sd-mdata-service']

    logger.debug(f'Final list of Repos in the glcp org')
    for i in repos:
        if i not in repo_exclude_list:
            # default_branch: str = gh_obj.get_default_branch(i)
            final_repo_list.append(i)
            # print(f'{counter}: {i} {default_branch}')
            print(f'{counter}: {i}')
            counter+=1

    # Calculate original pr template md5sum
    original_pr_template_file_path=['files/PULL_REQUEST_TEMPLATE.md']
    original_md5=calc_template_md5sum(gh_obj.get_pr_template_file_content('org-policies',original_pr_template_file_path))


    # final_repo_list=['sridhar-py','aws-hpe_onepass_2_dev-config']  # TODO remove
    counter : int = 1
    for repos in final_repo_list:
        print(f'{counter}: {repos}')
        counter+=1

    repos_to_be_updated=[]
    counter : int = 1
    template_file_names=['.github/PULL_REQUEST_TEMPLATE.md','.github/pull_request_template.md']
    for i in final_repo_list:
        if gh_obj.check_is_repo_archived(i):
            logger.info(f'Repo "{i}" is Archived ...Skipping')
            continue
        logger.debug(f' {counter}: repo {i} is being processed.')
        counter+=1
        pr_template_name=gh_obj.check_pull_request_template(i)
        pr_template=get_template_path(pr_template_name,i)
        if not pr_template_name:
            git_clone(org_name,i,token)
            git_push(i,pr_template,token)
            repos_to_be_updated.append(i) 
        else:
            logger.info(f'Pull Request Template file exsists for repo {i}')
            user_template_md5=calc_template_md5sum(gh_obj.get_pr_template_file_content(i,template_file_names))
            if original_md5!=user_template_md5:
                logger.debug(f'md5sum of master template file pull_request_template {original_md5}')
                logger.debug(f'md5sum of user repo {i} pull_request_template {user_template_md5}')
                git_clone(org_name,i,token)
                ec,out,err=mu.run_cmd(f'ls -ld {os.path.dirname(__file__)}/../{i}',shell=True,logger=logger)
                logger.debug(f'stdout: {out}')
                logger.debug(f'stderr: {err}')    
                git_push(i,pr_template,token)
                mu.run_cmd(f'rm -rf {os.path.dirname(__file__)}/../{i}',shell=True,logger=logger)
                repos_to_be_updated.append(i)
            else:
                logger.debug(f'md5sum of master repo and user repo {i} PR template is same,skipping....')

    logger.debug(f'repos to be updated with pull_request_template are {repos_to_be_updated}')

    mu.create_log_file(module_name=module_name, module_description=module_description,
                count_final_repo_list=len(final_repo_list), count_repo_exclude_list=len(repo_exclude_list),
                 repos_to_be_updated=repos_to_be_updated)

def get_template_path(pr_template_name,repo_name):
    default_template_name='PULL_REQUEST_TEMPLATE.md'
    # template_file_name=['pull_request_template.md',default_template_name]    
    if pr_template_name:
        pr_template=f'{os.path.dirname(__file__)}/../{repo_name}/.github/{pr_template_name}'
        return pr_template
    return f'{os.path.dirname(__file__)}/../{repo_name}/.github/{default_template_name}'


def calc_template_md5sum(pr_template_content):
    pr_template_md5 = hashlib.md5(pr_template_content).hexdigest()
    return pr_template_md5

    
def git_clone(org_name: str, repo_name: str,token):
    print(f"git cloning the repo")
    git_url=f'https://x-access-token:{token}@github.com/{org_name}/{repo_name}.git'
    cmd=f'git clone {git_url}'
    ec,out,err=mu.run_cmd(cmd,shell=True,logger=logger)
    if ec > 0:
        logger.error(f'cmd failed with exit code: {ec}')
        logger.error(f'stdout: {out}')
        logger.error(f'stderr: {err}')
        update_csv_file(repo_name, err)
        # sys.exit(1)

def git_push(repo_name: str, pr_template, token):
    pr_template_path=f'{os.path.dirname(__file__)}/../{repo_name}/.github'
    mu.mkdir_p(pr_template_path)
    cmds=[f'cp -fp {os.path.dirname(__file__)}/../files/PULL_REQUEST_TEMPLATE.md {pr_template}',
            f'cd {repo_name}; git add -f {pr_template}']

    for cmd in cmds:
        ec, out, err = mu.run_cmd(cmd, shell=True, logger=logger)
        if ec > 0:
            logger.error(f'cmd failed with exit code: {ec}')
            logger.error(f'stdout: {out}')
            logger.error(f'stderr: {err}')
            update_csv_file(repo_name, err)
           # sys.exit(1)   
    

    cmd=f'cd {repo_name}; git status'
    ec, out, err = mu.run_cmd(cmd, shell=True, logger=logger)
    if ec != 0:
        logger.error(f'cmd failed with exit code: {ec}')
        logger.error(f'stdout: {out}')
        logger.error(f'stderr: {err}')
        update_csv_file(repo_name, err)
        # sys.exit(1)


    if not 'modified:' in out and not 'new file:' in out:
        logger.debug(f'No change to the template file in the repo {repo_name} ,skipping....')
        return

    cmds = [
            f'ls',
            f'echo "[skip actions] PR Template Enforcement. Please contact glcp-giotto@hpe.com for any clarifications" > pr_commit',
            f'git config --global user.email "glcp-giotto@hpe.com"',
            f'git config --global user.name "Automation"',
            f'''cd {repo_name}; git commit {pr_template} -F ../pr_commit ''',
            f'cd {repo_name}; git push'
           ]

    for cmd in cmds:
        ec, out, err = mu.run_cmd(cmd, shell=True, logger=logger)
        if ec > 0:
           logger.error(f'cmd failed with exit code: {ec}')
           logger.error(f'stdout: {out}')
           logger.error(f'stderr: {err}')
           update_csv_file(repo_name, err)
           # sys.exit(1)

def contains_sequence(main_string, sequence):
    return all(word in main_string for word in sequence)

def update_csv_file(repo_name: str, error_msg):
    '''This function updates the error log details to the csv file'''
    with open('error_log.csv', mode='a', newline='') as csv_file:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fieldnames = ['Repository Name', 'Error Message', 'Timestamp']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        # Check if the file is empty and write header if needed
        if csv_file.tell() == 0:
            writer.writeheader()
        # Write error details to the CSV file
        sequence_to_check = ["GH006", "Protected branch update failed for", "a/"]
        if contains_sequence(error_msg, sequence_to_check):
            error_msg = "Failed to update the org-policies due to branch protection rule"
            writer.writerow({'Repository Name': repo_name, 'Error Message': error_msg, 'Timestamp': timestamp})
        else:
            writer.writerow({'Repository Name': repo_name, 'Error Message': error_msg, 'Timestamp': timestamp})
        csv_file.close()
