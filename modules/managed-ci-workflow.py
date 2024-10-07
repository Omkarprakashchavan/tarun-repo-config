# Import hashlib library (md5 method is part of it)
import hashlib
import logging
import os
import sys
from typing import Dict, List, Union
from datetime import datetime

import yaml
from ruamel.yaml import YAML

sys.path.append(f'{os.path.dirname(__file__)}/..')
import subprocess
import utils.myutils as mu
from utils.myutils import file_exists, mkdir_p
from utils.github_apis import GitHubAPIs
from os import listdir
from os.path import isfile, join


logger: Union[logging.Logger, None] = None

topdir = os.path.dirname(os.path.abspath(sys.argv[0]))
logdir = f'{topdir}/logdir'
file_name_pattern='managed-ci'

def main(module_name='',
         module_description='',
         repositories=[],
         default_managed_refspec=None):
    if not 'ORG_NAME' in os.environ:
        org_name='glcp'
    else:
        org_name=os.environ['ORG_NAME']
    managed_ci_workflow_repo='managed-ci-workflow'

    app_token = os.environ.get("GITHUB_APP_TOKEN", '')
    # pull_request_token=os.environ.get("GIT_PR_TOKEN", '')

    mu.mkdir_p(logdir)
    global logger
    ## Change values accordingly in get_logger()
    logger = mu.get_logger('workflow-deployer', f'{logdir}/workflow-deployer.log', level='debug', output_to_console=True)
    gh_obj = GitHubAPIs(org_name='glcp', token=app_token, logger=logger)
    org_repos : List[str] = gh_obj.get_repo_names_in_org()

    logger.debug(f'Final list of Repos in the glcp org')
    for rep in repositories:
        r = rep.get('name')
        if r not in org_repos:
            raise Exception(f"Repository {r} not found in {org_name} organization")

    sq_data: Dict[str, List[Dict[str,str]]] = \
        sonarqube_config(org_name=org_name)
    num_sq_projects = len(sq_data['Projects'])

    new_deploys={}
    old_deploys={}
    for repo in repositories:
        r = repo.get('name')
        refspec = repo.get('refspec', default_managed_refspec)
        optional_workflows_requested = repo.get('optional_workflows', [])

        if gh_obj.check_is_repo_archived(r):
            logger.info(f'Repo "{r}" is Archived ...Skipping')
            continue

        # Clone participating project repo
        git_clone(org_name, r, app_token)

        # Clone managed-ci-workflow and checkout a specific refspec within the project repo directory.
        # Retieve workflows from manifest file.
        git_clone(org_name, managed_ci_workflow_repo, app_token, refspec=refspec, directory=r)
        versioned_ci_repo = f'{os.path.dirname(__file__)}/../{r}/{managed_ci_workflow_repo}'

        template_workflow_path =f'{versioned_ci_repo}/templates'
        primary_workflow_path =f'{versioned_ci_repo}/workflows'
        workflow_manifest_file =f'{versioned_ci_repo}/workflow-manifest.yaml'
        # print(f'template_workflow_path: {template_workflow_path}')
        # print(f'primary_workflow_path: {primary_workflow_path}')
        # print(f'workflow_manifest_file: {workflow_manifest_file}')

        primary_workflows, optional_workflows, template_workflows = workflow_manifest(workflow_manifest_file)
        # print(f'primary workflows: {primary_workflows}')
        # print(f'template workflows: {template_workflows}')

        workflow_sources=[]
        workflow_exists=[]
        for twf in template_workflows:
            if not gh_obj.check_workflow_file(r, twf):
                # File does not exist, exists at 0 bytes, or other exception
                workflow_sources.append(f'{template_workflow_path}/{twf}')
            else:
                workflow_exists.append(f'{template_workflow_path}/{twf}')
        for owf in optional_workflows:
            if owf not in optional_workflows_requested:
                continue
            source = f'{primary_workflow_path}/{owf}'
            dest = get_dest_workflow_path(r, owf)
            logger.debug(f'comparing optional workflow {source} vs. {dest}')
            if not gh_obj.check_workflow_file(r, owf):
                # File does not exist, exists at 0 bytes, or other exception
                logger.debug(f'workflow {owf} does not exist in {r}')
                workflow_sources.append(f'{primary_workflow_path}/{owf}')
            else:
                logger.info(f'optional workflow file {owf} exists for repo {r}')
                source_md5sum = calc_template_md5sum(f'{primary_workflow_path}/{owf}')
                dest_md5sum = calc_template_md5sum(dest)
                logger.debug(f'md5sum of source optional workflow file {source_md5sum}')
                logger.debug(f'md5sum of user repo {r} optional workflow file {dest_md5sum}')
                if not source_md5sum == dest_md5sum:
                    workflow_sources.append(f'{primary_workflow_path}/{owf}')
                    logger.debug(f'need to deploy source optional workflow file to repo "{r}"')
                else:
                    workflow_exists.append(f'{primary_workflow_path}/{owf}')
                    logger.debug(f'md5sum of master repo and user repo {r} workflow is the same.  skipping deployment.')
        for pwf in primary_workflows:
            source = f'{primary_workflow_path}/{pwf}'
            dest = get_dest_workflow_path(r, pwf)
            logger.debug(f'comparing primary workflow {source} vs. {dest}')
            if not gh_obj.check_workflow_file(r, pwf):
                # File does not exist, exists at 0 bytes, or other exception
                logger.debug(f'workflow {pwf} does not exist in {r}')
                workflow_sources.append(f'{primary_workflow_path}/{pwf}')
            else:
                logger.info(f'primary workflow file {pwf} exists for repo {r}')
                source_md5sum = calc_template_md5sum(f'{primary_workflow_path}/{pwf}')
                dest_md5sum = calc_template_md5sum(dest)
                logger.debug(f'md5sum of source primary workflow file {source_md5sum}')
                logger.debug(f'md5sum of user repo {r} primary workflow file {dest_md5sum}')
                if not source_md5sum == dest_md5sum:
                    workflow_sources.append(f'{primary_workflow_path}/{pwf}')
                    logger.debug(f'need to deploy source primary workflow file to repo "{r}"')
                else:
                    workflow_exists.append(f'{primary_workflow_path}/{pwf}')
                    logger.debug(f'md5sum of master repo and user repo {r} workflow is the same.  skipping deployment.')
        # print(workflow_sources)
        git_push_workflows(r, workflow_sources, app_token)

        # Add to the dict of new deployments for the report
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        old_deploys[r] = {}
        old_deploys[r]['refspec'] = refspec
        old_deploys[r]['workflows'] = [{'name': os.path.basename(wf)} for wf in workflow_exists]
        new_deploys[r] = {}
        new_deploys[r]['refspec'] = refspec
        new_deploys[r]['workflows'] = [{'name': os.path.basename(wf), 'updated': timestamp} for wf in workflow_sources]

        sonarqube_config(sq_data, r, gh_obj.get_default_branch(r))

    if len(sq_data['Projects']) > num_sq_projects:
        sonarqube_config(sq_data, save=True)
    else:
        logger.debug('nothing to push... all repos are present in the SonarQube config file')

    update_log_file(new_deploys=new_deploys, old_deploys=old_deploys)

    wf_cleanup(primary_workflows=primary_workflows, template_workflows=template_workflows, optional_workflows=optional_workflows, repo_name=r)


def workflow_manifest(manifest_file):
    with open(manifest_file, "r") as f:
        data = yaml.safe_load(f)
    return data.get('primary_workflows', []), data.get('optional_workflows', []), data.get('template_workflows', [])


def wf_cleanup(primary_workflows=[], template_workflows=[], optional_workflows=[], repo_name=''):
     # This function will remove the files from the remote repo if the files are not mentioned 
    # in the manifest file  and the file names start with file name pattern 'managed-ci'.
    workflow_dir=f'{os.path.dirname(__file__)}/../{repo_name}/.github/workflows'
    wf_files_in_user_repo = [f for f in listdir(workflow_dir) if isfile(join(workflow_dir, f))]
    wf_names=primary_workflows + template_workflows + optional_workflows
    wf_files_to_be_deleted=[]
    for i in wf_files_in_user_repo:
        if i in wf_names:
            logger.debug(f'This file {i} is being skipped from deletion because this file is in the manifest')
            continue
        if i.startswith(file_name_pattern):
            logger.debug(f'This file {i} is being added to deletion list because this file is not the manifest and it starts with {file_name_pattern} pattern')
            wf_files_to_be_deleted.append(i)
        else:
            logger.debug(f'This file {i} is being skipped from deletion list because this files are from user repo')
    for i in wf_files_to_be_deleted:
        logger.debug(f'WF File to be deleted: {i}')
        cmds=[f'cd {workflow_dir}; git rm {i}']
        cmds = [
            f'cd {workflow_dir}; git rm {i}',
            f"cd {repo_name}; git commit -m '[skip actions] delete workflow(s) {i}'"
           ]
        for cmd in cmds:
            ec, out, err = run_subprocess(cmd)
            if ec:
                logger.error(f'{cmd} failed with exit code: {ec}')
                logger.error(f'stdout: {out.decode()}')
                logger.error(f'stderr: {err.decode()}')
                sys.exit(1)
    cmd=f'cd {repo_name}; git push' 
    ec, out, err = run_subprocess(cmd)
    if ec:
        logger.error(f'{cmd} failed with exit code: {ec}')
        logger.error(f'stdout: {out.decode()}')
        logger.error(f'stderr: {err.decode()}')
        sys.exit(1)


def get_dest_workflow_path(repo_name, workflow):
    workflow_path=f'{os.path.dirname(__file__)}/../{repo_name}/.github/workflows/{workflow}'
    if mu.file_exists(workflow_path, check_nonzero_filesize=True):
        return workflow_path
    return None


def calc_template_md5sum(pr_template):
    with open(pr_template, 'rb') as fh:
        data = fh.read()
        pr_template_md5 = hashlib.md5(data).hexdigest()
    return pr_template_md5


def git_clone(org_name: str, repo_name: str, token: str, refspec=None, directory=None):
    logger.debug(f"git clone {org_name}/{repo_name}")
    git_url=f'https://x-access-token:{token}@github.com/{org_name}/{repo_name}.git'
    cmd=f'git clone {git_url}'
    if directory:
        cmd=f'cd {directory}; {cmd}'
    if refspec:
        cmd=f'{cmd}; cd {repo_name}; git checkout {refspec}'
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
    out, err = proc.communicate()
    ec = proc.returncode
    if ec > 0:
        logger.error(f'cmd failed with exit code: {ec}')
        logger.error(f'stdout: {out.decode()}')
        logger.error(f'stderr: {err.decode()}')
        sys.exit(2)


def run_subprocess(cmd: str, abort_on_error=False):
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
    out, err = proc.communicate()
    ec = proc.returncode
    if ec > 0:
        logger.error(f'cmd: {cmd}')
        logger.error(f'exit code: {ec}')
        logger.error(f'stdout: {out.decode()}')
        logger.error(f'stderr: {err.decode()}')
        if abort_on_error:
            raise Exception(f'the cmd "{cmd}" failed... see stdout/stderr above')
    else:
        logger.debug(f'stdout: {out.decode()}')
    return ec, out, err


def git_push_workflows(repo_name: str, workflow_sources: List, token):
    workflow_dest=f'{os.path.dirname(__file__)}/../{repo_name}/.github/workflows'
    mu.mkdir_p(workflow_dest)
    wf_basenames = []

    # Copy workflow sources to participating repository.   Add to git.
    for wf in workflow_sources:
        filename = os.path.basename(wf)
        wf_basenames.append(filename)
        cmds=[f'cp -fp {wf} {workflow_dest}/{filename}',
              f'cd {workflow_dest} && git add -f {filename}']
        for cmd in cmds:
            ec, out, err = run_subprocess(cmd)
            if ec:
                sys.exit(1)

    # Drop out if git status indicates that nothing has changed
    cmd=f'cd {repo_name}; git status'
    ec, out, err = run_subprocess(cmd)
    if ec:
        sys.exit(1)
    if not 'modified:' in out.decode() and not 'new file:' in out.decode():
        logger.debug(f'No workflow changes for repo {repo_name}. Skipping.')
        return

    # Commit and push
    wf_push_list = ', '.join(wf_basenames)
    cmds = [
            f"cd {repo_name}; git commit -m '[skip actions] added/updated workflow(s) {wf_push_list}'",
            f'cd {repo_name}; git push'
           ]
    for cmd in cmds:
        ec, out, err = run_subprocess(cmd)
        if ec:
            sys.exit(1)


def sonarqube_config(data=None, repo_name=None, default_branch_name=None,
                     org_name=None, save=False) -> Union[Dict[str, List[Dict[str,str]]], None]:
    """
    This function operates in 3 modes:
      1. Retrieve the existing SonarQube config from the "devx-sonarqube" repo
          if the "data" param is None
      2. Write the updated SonarQube config changes ("data" param) back to the
          SonarQube config YAML file and push the changes if the "save" param is True.
      3. Update the SonarQube config data struct ("data" param) if the repo
          name and default branch name are provided
    """

    sq_repo_name = 'devx-sonarqube'
    filename = os.environ.get('SQ_CONFIG_FILENAME', 'sonar.yaml')
    yaml_filename = f'{sq_repo_name}/sonarqube-management/sonar_data/{filename}'
    yaml = YAML()

    if not data:
        git_clone(org_name, sq_repo_name, os.environ["GITHUB_APP_TOKEN"],
                  refspec=os.environ.get('SQ_BRANCH_NAME', None))
        with open(yaml_filename, 'rb') as fh:
            data = yaml.load(fh)
        return data

    if save:
        logger.debug(f'updating SonarQube config file "{yaml_filename}" ...')
        yaml.indent(mapping=2, sequence=4, offset=2)
        with open(f'{yaml_filename}', 'wb') as fh:
            yaml.dump(data, fh)
        git_push_sonarqube_config(yaml_filename, sq_repo_name)
        # the GitHub Action that invoked this Python script will check for the
        # existence of this file.  If this file exists, then the
        # workflow "sonar.yaml" in the "devx-sonarqube" GitHub repo will be invoked
        logger.debug(f'creating "need-sq-onboarding.txt" ...')
        with open('need-sq-onboarding.txt', 'w') as fh:
            fh.write('yes please')
        return

    projects: List[Dict[str, str]] = data['Projects']
    if not any(d['name'] == repo_name for d in projects):
        logger.debug(f'repo "{repo_name}" not found in SonarQube config; adding it...')
        projects.append({'name': repo_name,
                         'branch': default_branch_name,
                         'qualitygate': 'glcp-sonarqube'})
    else:
        logger.debug(f'repo "{repo_name}" found in SonarQube config; nothing to do...')


def git_push_sonarqube_config(yaml_filename: str, repo_name: str) -> None:
    """
    Push the updated SonarQube config changes to the "devx-sonarqube" repo
    """

    yaml_path = yaml_filename.rsplit('/', 1)[0]
    filename = yaml_filename.rsplit('/', 1)[1]

    cmds = [
            (f'cd {yaml_path}; '
             f'git commit -m "[skip actions] Onboarding repo(s)" {filename}'
            ),
            f'cd {repo_name}; git push'
           ]
    for cmd in cmds:
        run_subprocess(cmd, abort_on_error=True)


def update_log_file(new_deploys, old_deploys, report_filename=f'devops-reports/workflow-reports/workflows-deployed.yaml'):
    mkdir_p(os.path.dirname(report_filename))

    print(yaml.dump(new_deploys, default_flow_style=False))

    if mu.file_exists(report_filename):
        with open(report_filename,'r') as report_f:
            try:
                report = yaml.safe_load(report_f).get('repositories', {})
            except AttributeError:
                report = {}
            '''
            This hack of a block ensures that the report includes references to workflows even if we have
            not deployed to them on this run.
            '''
            for repo in old_deploys.keys():
                # if this repo is not present in the existing report, append it and move on to the next
                if repo not in report.keys():
                    report.update({repo: old_deploys[repo]})
                    continue
                # for each of the already deployed workflows, check to see if its name is in the workflow list
                # of the current repo.  If not, append it.
                for wf in old_deploys.get(repo, {}).get('workflows', []):
                    if wf.get('name') not in [x.get('name') for x in report.get(repo, {}).get('workflows', [])]:
                        report[repo]['workflows'].append(wf)
            for repo in new_deploys.keys():
                # if this repo is not present in the existing report, append it and move on to the next
                if repo not in report.keys():
                    report.update({repo: new_deploys[repo]})
                    continue
                # we're working with a repo that is already in the report.
                # - if we have deployed an existing workflow, update the 'updated' field
                # - if this is a new workflow, add the workflow name and deployment update fields
                for wf in new_deploys.get(repo, {}).get('workflows', []):
                    matched = False
                    for report_wf in report.get(repo, {}).get('workflows', []):
                        if report_wf.get('name') == wf.get('name'):
                            report_wf['updated'] = wf.get('updated')
                            matched = True
                            break
                    if not matched:
                        report[repo]['workflows'].append(wf)
    else:
        report = new_deploys

    with open(report_filename, mode = 'w') as report_f:
        report_f.write(yaml.dump({'repositories': report}, default_flow_style=False, sort_keys=False))
