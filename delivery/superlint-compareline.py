import re
import sys

diff_file = 'git-diff.txt'
lint_logfile = 'lint-output.log'
file_lines_dict = {}
words = ['^diff', '^\+\s+', '^\-\s+', '^\+\d+', '^\-\d+', '^\-+', '^\++']
dictname = ''

def line_starts_with_any_word(line, words):
    return any(re.match(word, line) for word in words)

with open(diff_file, 'r', encoding="utf8") as file:
    for line_number, line in enumerate(file, start=1):
        line = line.strip()
        if line_starts_with_any_word(line, words):
            if line.startswith('diff'):
                dictname = (line.split(" ")[-1])[2:]
                cleaned_line = dictname.strip().replace('/github/workspace/', '')
                if dictname not in file_lines_dict.keys():
                    file_lines_dict[dictname] = []
            else:
                line_num = re.findall(r'^[+-]\s*(\d+)', line)
                for ln in line_num:
                    file_lines_dict[dictname].append(int(ln))

error_dict = {key: [] for key in file_lines_dict}
print(f'Before lint output {error_dict}')
unique_file_lines_dict = {key: list(set(value)) for key, value in file_lines_dict.items()}
line_num_pattern = r'\b\d+:'#\d+\b'

with open(lint_logfile, 'r', encoding="utf8") as file:
    for line in file:
        if re.search('error', line, re.IGNORECASE):
            # print(line)
            line_list = line.split(' ')
            filename = [word for word in line_list if '/' in word]
            if len(filename) > 0:
                # print(filename)
                filename = str(filename).strip().replace('/github/workspace/', '').replace('[', '').replace("'",'').replace(']','')
                error_filename = filename.split(':')[0]
                # print(error_filename)
                for word in line_list:
                    # print(word)
                    result = None
                    match = re.search(line_num_pattern, word)
                    if match:
                        result = match.group().split(':')[0]
                        # print(filename, error_filename, match, int(result))
                        break
                if error_filename in error_dict:
                    if result not in error_dict[error_filename]:
                        error_dict[error_filename].append(int(result))
        if "line " in line:
            match = re.search(r'In (.+) line (\d+):', line)
            if match:
                file_path = match.group(1)
                line_number = match.group(2)
                file_path = file_path.strip().replace('/github/workspace/', '')
                if file_path in error_dict:
                    if line_number not in error_dict[file_path]:
                        error_dict[file_path].append(int(line_number))
        # if line.startswith('  on '):
        #     line_data = line.split(' ')
        #     error_filename = line_data[3]
        #     error_line = line_data[5][:-1]
        #     print(line, error_filename, error_line)
        #     if error_filename in error_dict:
        #         if error_line not in error_dict[error_filename]:
        #             error_dict[error_filename].append(error_line)

lint_file = open(lint_logfile, 'r')
lint_data = lint_file.read()
# print(lint_data)
tf_pattern = r'^  on (\S+) line (\d+),.*?\n((?:\s+\d+:\s+.*?\n)*)(?=\n\s*\n|$)'
# go_pattern = r'Error:\s+(\S+):(\d+):\d+'
go_pattern = r'(?P<filename>.+\.go):(?P<line_number>\d+):'
tf_matches = re.finditer(tf_pattern, lint_data, re.MULTILINE | re.DOTALL)
# go_matches = re.findall(go_pattern, lint_data)
go_matches = re.finditer(go_pattern, lint_data)
print(f'Printing Go matches ----------- {go_matches}')

for match in tf_matches:
    filename = match.group(1)
    line_number = int(match.group(2))
    lines = match.group(3).strip().split('\n')
    line_numbers = [int(re.search(r'\d+', line).group()) for line in lines if line.strip() and re.search(r'\d+', line)]
    updated_line_num = [int(line_number) - i for i in range(5, 0, -1)] + [int(line_number)] + [int(line_number) + i for i in range(1, 6)]
    print(f"This is for TERRAFORM filename = {filename} line_numbers = {updated_line_num}")
    if filename in error_dict:
        error_dict[filename].extend(list(set(line_numbers)))

for match in go_matches:
    filename = match.group('filename')
    filename = filename.replace('Error: ', '')
    line_number = int(match.group('line_number'))
    updated_line_num = [int(line_number) - i for i in range(5, 0, -1)] + [int(line_number)] + [int(line_number) + i for i in range(1, 6)]
    # print(f"Filename: {filename}, Line Number: {line_number}, {updated_line_num}")
    if filename in error_dict:
        updated_line_num = [int(line_number) - i for i in range(5, 0, -1)] + [int(line_number)] + [int(line_number) + i for i in range(1, 6)]
        print(f"This is for GOLANG {filename}, {updated_line_num}")
        error_dict[filename].extend(list(set(updated_line_num)))

# for match in go_matches:
#     filename, line_number = match
#     updated_line_num = [int(line_number) - i for i in range(5, 0, -1)] + [int(line_number)] + [int(line_number) + i for i in range(1, 6)]
#     print(filename, line_number, updated_line_num)
#     if filename in error_dict:
#         updated_line_num = [int(line_number) - i for i in range(5, 0, -1)] + [int(line_number)] + [int(line_number) + i for i in range(1, 6)]
#         print(f"This is for GOLANG {filename}, {updated_line_num}")
#         error_dict[filename].extend(list(set(updated_line_num)))

error_dict = {key: list(set(value)) for key, value in error_dict.items()}
print(f'After lint output {error_dict}')
output_dict = {}
for key in error_dict.keys():
    if key in file_lines_dict:
        if str(key).endswith('.go'):
            print(f'Go file found: {key}')
            output_dict[key] = error_dict[key]
        else:
            common_values = set(error_dict[key]) & set(file_lines_dict[key])
            output_dict[key] = common_values
            # print(f"'{key} having linting error on line': {common_values}")

for key in output_dict.keys():
    if output_dict[key]:
        print(f"'{key} having linting error on line': {output_dict[key]}")

any_non_empty = any(errors for errors in output_dict.values())
if any_non_empty:
    sys.exit(1)
