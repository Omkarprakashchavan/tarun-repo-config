#!/usr/bin/env python3
import smtplib
import ssl
import os
import csv
import sys
import re
import yaml
from os.path import basename
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Open the CSV file for reading
csvfilename = 'all-repos.csv'
yaml_file = 'workflow-deployer.yaml'

def get_env(key='', if_fail=False):
    '''This function fetches value environment variable'''
    try:
        value = os.environ[key]
        return value
    except KeyError as ke:
        print(f"Environment variable not found {str(ke)}")
        if (if_fail):
            return ''
        exit(1)

def updatefile(se_content='', re_content='', se_link='', re_link=''):
    '''This function updates the content of the HTML file'''
    html_file = 'email_format.html'
    try:
        with open(html_file, 'r+') as f:
            file = f.read()
            file = re.sub(se_content, re_content, file)
            file = re.sub(se_link, re_link, file)
            f.seek(0)
            f.write(file)
            f.truncate()
            return file
    except FileNotFoundError as fnfe:
        print(f'File {html_file} not found. Error: {fnfe}')

def main():
    try:
        with open(csvfilename, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            developer_email_list = []
            manager_email_list = []
            with open(yaml_file, 'r') as file:
                parsed_yaml = yaml.safe_load(file.read())
                repositories = []
                modules = parsed_yaml.get('modules', [])
                for module in modules:
                    repositories.extend([repo['name'] for repo in module.get('repositories', [])])
            for row in reader:
                if row['Repo name'] in repositories:
                    developer_email_list.append(row['Developer'])
                    manager_email_list.append(row['Manager'])
        developer_email_list = list(set(developer_email_list))
        manager_email_list = list(set(manager_email_list))
    except FileNotFoundError as fnfe:
        print(f'File {csvfilename} not found. Error: {fnfe}')
        sys.exit(1)
    except KeyError as ke:
        print(f'Key Error {ke}')
        sys.exit(1)

    msg = MIMEMultipart()
    msg['From'] = get_env('EMAIL_FROM', False)
    msg['To'] = ','.join(developer_email_list)
    msg['Cc'] = ','.join(manager_email_list)
    msg['Subject'] = f"{os.environ['SUBJECT']}"
    email_server_uname = get_env('EMAIL_SERVER_USERNAME', False)
    email_server_pwd = get_env('EMAIL_SERVER_PASSWORD', False)
    email_server_name = get_env('EMAIL_SERVER_NAME', False)
    email_server_port = get_env('EMAIL_SERVER_PORTNUM', False)
    email_from = get_env('EMAIL_FROM', False)
    replace_context = get_env('EMAIL_CONTEXT', True)
    replace_link = get_env('EMAIL_LINK', True)
    search_context = 'FIRST_CONTEXT'
    search_link = 'https://github.com/glcp'
    
    # html_content = open("email_format.html", "r")
    # html = html_content.read()
    html = updatefile(search_context, replace_context, search_link, replace_link)
    part = MIMEText(html, 'html')
    msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(email_server_name, int(email_server_port), context=context) as s:
        s.login(email_server_uname, email_server_pwd)
        s.send_message(msg, from_addr=email_from)
        s.quit()

main()
