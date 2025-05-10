import json
import subprocess
import re
import time
from pathlib import Path


class LazyDecoder(json.JSONDecoder):
    def decode(self, s, **kwargs):
        regex_replacements = [
            (re.compile(r'([^\\])\\([^\\])'), r'\1\\\\\2'),
            (re.compile(r',(\s*])'), r'\1'),
        ]
        for regex, replacement in regex_replacements:
            s = regex.sub(replacement, s)
        return super().decode(s, **kwargs)

def get_answer_without_think(content):
    if '</think>' in content:
        content = content.split("</think>")[1]
    content = content.strip()
    start = content.find('{')
    end = content.rfind('}')
    if start != -1 and end != -1 and end > start:
        return content[start:end+1]
    return content

def get_answer_as_json(content):
    answer = get_answer_without_think(content)
    try:
        return json.loads(answer)
    except json.JSONDecodeError as e:
        raise

def call_getcode(args: dict, json_file: str) -> str:
    """调用getcode.py工具查询代码信息"""
    args_list = [item for pair in args.items() for item in pair]
    cmd = ['python', 'getcode.py', '--json', json_file]
    cmd += args_list
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"getcode.py failed: {result.stderr}")
    result_json = json.loads(result.stdout.strip())

    if 'notfound' in result_json:
        print(f"所请求的符号不存在：{args}")
    return result_json

def save_json(json_data, output_file: Path):
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2)
            
        print(f"JSON已保存: {output_file}")
    except OSError as e:
        print(f"JSON文件保存失败: {str(e)}")

def codehub_issue_submit(title: str, desc: str):
    # 向codehub发起issue
    cmd = ['python', 'codehub_issue.py', '--title', title, "--desc", desc, "--project", "test"]
    result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True
                    )
    return result.stdout

def log_file_save(file: str, log: str):
    try:
        with open(file, 'a') as f:
            f.write(log)
            f.flush()
    except Exception as e:
        print(f"文件：{file} 保存失败，log:{log}")

# 过程日志打印
STAR = "\u2B50"
RIGHT = "\u2705"
WRONG = "\u274E"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
def process_log(msg):
    print(f"{GREEN}{RIGHT}{RESET} {msg}")
    time.sleep(0.1)

def tools_log(msg):
    print(f"{YELLOW}{STAR}{RESET} 调用工具: {msg}")
    time.sleep(0.1)

def error_log(msg):
    print(f"{RED}{WRONG}{RESET} 程序错误终止：{msg}")
    time.sleep(0.5)
