import os
import glob
import re
import subprocess
import json
import requests
from typing import Optional, Dict, List, Any
from git import Repo
from pathlib import Path

def parse_config_line(line: str) -> Optional[tuple[str, str]]:
    """解析配置文件中的一行，提取键值对"""
    line = line.strip()
    if not line or line.startswith('#'):  # 跳过空行和注释
        return None

    if '=' in line:
        key, value = line.split('=', 1)
        return key.strip(), value.strip()
    return None

def read_config_values(file_path: str) -> Dict[str, str]:
    """读取配置文件中的所有键值对"""
    config = {}
    try:
        if not os.path.exists(file_path):
            print(f"错误: 文件 '{file_path}' 不存在")
            return config

        with open(file_path, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                parsed = parse_config_line(line)
                if parsed:
                    key, value = parsed
                    config[key] = value
    except Exception as e:
        print(f"读取文件时出错: {e}")
    return config

def get_value_by_key(file_path: str, key: str) -> Optional[str]:
    """根据键获取配置文件中的值"""
    config = read_config_values(file_path)
    return config.get(key)

def get_config(app_name: str):
    config_file = os.path.dirname(__file__) + '/assistant.conf'
    src_url = get_value_by_key(config_file, app_name + "_src_url")
    src_url_proxy = get_value_by_key(config_file, app_name + "_src_url_proxy")
    commitID = get_value_by_key(config_file, app_name + "_commitID")
    src_branch_name = get_value_by_key(config_file, app_name + "_src_branch")
    dst_branch_name = get_value_by_key(config_file, app_name + "_dst_branch")
    dst_url = get_value_by_key(config_file, app_name + "_dst_url")
    project_url = get_value_by_key(config_file, app_name + "_project_url")
    project_token = get_value_by_key(config_file, app_name + "_project_token")
    mr_server = get_value_by_key(config_file, app_name + "_mr_server")

    return src_url, src_url_proxy, commitID, src_branch_name, dst_branch_name, dst_url, project_url, project_token, mr_server

def save_config(key, new_value):
    """
    修改配置文件中指定key对应的value值
    """
    config_file = os.path.dirname(__file__) + '/assistant.conf'
    try:
        # 读取文件内容
        with open(config_file, 'r') as file:
            lines = file.readlines()

        # 查找并修改目标行
        modified = False
        with open(config_file, 'w') as file:
            for line in lines:
                if line.startswith(f"{key}="):
                    file.write(f"{key}={new_value}\n")
                    modified = True
                else:
                    file.write(line)

        if not modified:
            with open(config_file, 'a') as file:
                file.write(f"{key}={new_value}\n")
            print(f"未找到键 '{key}'，已添加新的键值对")
        else:
            print(f"成功将键 '{key}' 的值修改为 '{new_value}'")

    except FileNotFoundError:
        print(f"错误：文件 '{config_file}' 不存在")
    except Exception as e:
        print(f"修改文件时发生错误：{str(e)}")

def generate_app_patches(app_name: str, commit_id: str, save_path: str) -> str:
    """
    拉取代码仓指定分支的最新代码并从指定的commitID开始生成所有patch。
    """
    src_url, _, commitID, src_branch_name, _, _, _, _, _ = get_config(app_name)
    if commit_id: # 如果用户指定了commit_id则以用户输入的值为基线
        commitID = commit_id

    local_repo_path = "/tmp/" + app_name + "-src"
    try:
        # 1. 克隆或更新仓库
        if not subprocess.run(["test", "-d", f"{local_repo_path}/.git"], capture_output=True).returncode == 0:
            # 如果目录不存在或不是git仓库，则克隆
            subprocess.run(["git", "clone", src_url, local_repo_path], check=True)
        else:
            # 如果是git仓库，则拉取最新代码
            subprocess.run(["git", "-C", local_repo_path, "fetch", "origin"], check=True)

        # 下载代码或更新代码后都走一边切换代码分支逻辑
        subprocess.run(["git", "-C", local_repo_path, "checkout", src_branch_name], check=True)
        subprocess.run(["git", "-C", local_repo_path, "pull", "origin", src_branch_name], check=True)
        
        # 2. 生成patch
        cmd = ["git", "-C", local_repo_path, "format-patch"]
        if commitID:
            cmd.append(f"{commitID}..HEAD")
        else:
            cmd.append("--all") # 从第一个commit开始

        cmd.extend(["--output-directory", save_path])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # 3. 获取最新的commitID并写入文件
        result = subprocess.run(["git", "-C", local_repo_path, "rev-parse", "HEAD"], 
                                stdout=subprocess.PIPE, text=True, check=True)
        last_commit_id = result.stdout.strip()
        save_config(app_name + "_last_commitID", last_commit_id)

        return f"成功从commit '{commitID or '第一个commit'}' 开始生成patch文件到 '{save_path}' 目录。"

    except subprocess.CalledProcessError as e:
        return f"Git操作失败: {e.stderr}"
    except Exception as e:
        return f"生成patch时发生错误: {e}"

def compress_patch(patch_content: str) -> str:
    """分析补丁内容，提取MR提交信息"""
    lines = patch_content.strip().split('\n')
    if not lines:
        return ''

    mr_lines = []
    in_mr_section = False
    signature_pattern = r'^--\s*$'  # 签名行通常以"-- "开头

    # 找到第一个非空行作为开始
    start_line = 0
    for i, line in enumerate(lines):
        if line.strip():
            start_line = i
            break

    for i, line in enumerate(lines):
        if i == start_line:
            in_mr_section = True
            mr_lines.append(line.strip())
            continue

        if in_mr_section:
            if re.match(signature_pattern, line):
                in_mr_section = False
                break
            if line.startswith('diff --git'):
                in_mr_section = False
                break
            mr_lines.append(line.strip())

    return '\n'.join(mr_lines)

def get_diff(input_str):
    marker = "Signed-off-by:"
    marker_index = input_str.find(marker)
    if marker_index == -1:
        return ""

    line_end_index = input_str.find('\n', marker_index)
    if line_end_index == -1:
        return ""

    return input_str[line_end_index + 1:]

def get_patch_count(app_name: str, commit_id: Optional[str] = None) -> int:
    """
    读取指定软件的补丁数量
    """
    directory = "/tmp/" + app_name + "-patchs"
    subprocess.run(["rm", "-rf", directory], check=True) # 清理/tmp/app_name-patchs目录
    os.makedirs(directory, exist_ok=True)
    generate_app_patches(app_name, commit_id, directory)
    path = Path(directory)
    return len([file for file in path.iterdir() if file.is_file()])

def find_patch_file(folder_path: str, number: int):
    """
    根据输入的编号查找对应命名的patch文件
    """
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        raise ValueError(f"文件夹路径不存在或不是一个有效的目录: {folder_path}")

    target_prefix = f"{number:04d}-"
    pattern = re.compile(rf"^{target_prefix}.*\.patch$")

    for filename in os.listdir(folder_path):
        if pattern.match(filename):
            return filename

    return None

def concat_commit_url(app_name, commit_id):
    """
    将仓库URL和提交ID拼接成完整的提交链接
    """
    _, src_url_proxy, _, _, _, _, _, _, _ = get_config(app_name)
    base_url = src_url_proxy.replace(f"/{app_name}.git", f"/{app_name}")
    return f"{base_url}/commit/{commit_id}"

def read_patch(app_name: str, patch_number: int) -> dict:
    """
    读取指定软件的补丁并按格式返回
    """
    try:
        result = {}
        directory = "/tmp/" + app_name + "-patchs"
        
        # 1. 查找补丁文件
        file_path = find_patch_file(directory, patch_number)
        
        # 2. **增加关键的返回值判断**
        if file_path is None:
            return {"读取补丁失败": f"在目录 '{directory}' 中未找到编号为 {patch_number} 的补丁文件。"}

        result["patch名"] = file_path
        
        # 3. 后续操作（只有在文件找到后才执行）
        if not os.path.isabs(file_path):
            full_path = os.path.join(directory, file_path)
        else:
            full_path = file_path

        with open(full_path, 'r', encoding='utf-8') as f:
            data = f.read()
            content = compress_patch(data)
            lines = content.split('\n')
            if lines: # 确保 lines 列表不为空
                first_line = lines[0].strip()
                parts = first_line.split()
                if len(parts) >= 2 and parts[0] == 'From':
                    result["提交信息"] = parts[1]
                    result["commit_url"] = concat_commit_url(app_name, parts[1])
            result["提交描述"] = content
            result["差异"] = get_diff(data)
            
    except Exception as e:
        # 保留通用异常捕获，以防其他未知错误
        return {"读取补丁失败": str(e)}

    return result

def remove_braces(data, indent=0):
    """递归处理JSON数据，去除大括号和中括号"""
    result = []
    indent_str = "  " * indent

    if isinstance(data, dict):
        for key, value in data.items():
            value_str = remove_braces(value, indent + 1)
            result.append(f"{key} {value_str}\n")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            item_str = remove_braces(item, indent + 1)
            result.append(f"{item_str}")
    else:
        return str(data)

    return "\n".join(result)

def get_patch_by_patch_name(patch_name, data):
    for patch in data:
        if patch.get("patch名") == patch_name:
            return patch
    return None

def extract_patches(data):
    filtered = [item for item in data if item.get("确认合入") == "是"]
    modules = {}
    for item in filtered:
        module = item.get("模块")
        patch_name = item.get("patch名")
        if module not in modules:
            modules[module] = []
        modules[module].append(patch_name)

    for module in modules:
        modules[module].sort()

    sorted_modules = sorted(modules.items(), key=lambda x: min(x[1]))
    result = [patches for module, patches in sorted_modules]
    return result

def create_local_new_branch_name(dst_branch_name: str, model: str) -> str:
    """
    根据给定的目标分支名称和模型名称创建新的本地分支名称
    """
    if 'release/' in dst_branch_name:
        new_branch = dst_branch_name.replace('release/', 'personal/')
        return f"{new_branch}/ai-patch_{model}"
    elif 'feature/' in dst_branch_name:
        new_branch = dst_branch_name.replace('feature/', 'personal/')
        return f"{new_branch}/ai-patch_{model}"
    elif 'personal/' in dst_branch_name:
        return f"{dst_branch_name}_patch_{model}"
    else:
        return f"personal/{dst_branch_name}/ai-patch_{model}"

def apply_patch(app_name: str, data: List[Dict]) -> str:
    """
    根据补丁分析内容将对应的patch合入到代码仓并提交至远端仓库
    """
    patch_name_list = extract_patches(data)

    results = ""
    result_failed = ""

    repo_url, _, _, _, dst_branch_name, dst_url, project_url, project_token, mr_server = get_config(app_name)

    patchs_directory = "/tmp/" + app_name + "-patchs"
    if not os.path.exists(patchs_directory):
        os.makedirs(patchs_directory, exist_ok=True)
        generate_app_patches(app_name, None, patchs_directory)

    local_dst_repo_path = "/tmp/" + app_name + "-dst"
    try:
        # 1. 克隆或更新目标代码仓库
        if not subprocess.run(["test", "-d", f"{local_dst_repo_path}/.git"], capture_output=True).returncode == 0:
            subprocess.run(["git", "clone", dst_url, local_dst_repo_path], check=True)
        else:
            subprocess.run(["git", "-C", local_dst_repo_path, "fetch", "origin"], check=True)

        # 切换分支
        subprocess.run(["git", "-C", local_dst_repo_path, "checkout", dst_branch_name], check=True)
        subprocess.run(["git", "-C", local_dst_repo_path, "pull", "origin", dst_branch_name], check=True)

    except subprocess.CalledProcessError as e:
        return f"Git操作失败: {e.stderr}"

    original_cwd = os.getcwd()
    try:
        os.chdir(local_dst_repo_path)

        for patch_names in patch_name_list:
            mr_message = {"补丁列表:": ["\r"], "改动分析:": ["\r"], "合入原因:": ["\r"]}
            title = ""
            title_flag = True
            commit_flag = True
            
            for patch_name in patch_names:
                patch_json = get_patch_by_patch_name(patch_name, data)
                if title_flag:
                    title = patch_json.get("补丁类型") + "[" + patch_json.get("模块") +"] " + "智能补丁回合\n"
                    title_flag = False
                
                patch_path = os.path.join(patchs_directory, patch_name)
                if not os.path.exists(patch_path):
                    result_failed += f"{patch_name} patch文件不存在\n"
                    break

                try:
                    # 使用git am应用patch
                    apply_result = subprocess.run(["git", "am", "--3way", patch_path], 
                                                capture_output=True, text=True, cwd=local_dst_repo_path)

                    if apply_result.returncode == 0:
                        mr_message["补丁列表:"].append(patch_name[5:])
                        mr_message["改动分析:"].append(f"{patch_name[5:]}<br>{patch_json.get('commit_url')}<br>{patch_json.get('改动说明')}<br>")
                        mr_message["合入原因:"].append(f"{patch_name[5:]}<br>{patch_json.get('确认理由')}<br>")
                    else:
                        subprocess.run(["git", "am", "--abort"], capture_output=True, text=True, cwd=local_dst_repo_path)
                        result_failed += f"{patch_json.get('提交信息')} patch冲突\n"
                        commit_flag = False
                except Exception as e:
                    result_failed += f"{patch_json.get('提交信息')} patch冲突: {str(e)}\n"
                    commit_flag = False
                    break
            
            if commit_flag:
                results += title + "合入成功\n"
                new_branch_name = create_local_new_branch_name(dst_branch_name, patch_json.get("模块"))
                
                # 如果目标分支已存在，删除目标分支
                subprocess.run(["git", "branch", "-D", new_branch_name], capture_output=True, text=True, cwd=local_dst_repo_path)
                # 创建本地模块粒度分支
                subprocess.run(["git", "branch", new_branch_name], check=True, capture_output=True, text=True, cwd=local_dst_repo_path)
                # 切换进入本地模块粒度分支
                subprocess.run(["git", "checkout", "-f", new_branch_name], check=True, capture_output=True, text=True, cwd=local_dst_repo_path)
                # 推送到远程
                subprocess.run(["git", "push", "--set-upstream", "origin", new_branch_name], check=True, capture_output=True, text=True, cwd=local_dst_repo_path)
                
                mr_url = create_mr(mr_server, project_url, project_token, new_branch_name, dst_branch_name, title, remove_braces(mr_message))
                results += "合并请求URL:" + mr_url + "\n"
                
                # 强制切换回本地分支
                subprocess.run(["git", "checkout", "-f", dst_branch_name], check=True, capture_output=True, text=True, cwd=local_dst_repo_path)
                # 清理本地分支，准备下一次循环
                subprocess.run(["git", "reset", "--hard", "origin/" + dst_branch_name], check=True, capture_output=True, text=True, cwd=local_dst_repo_path)
            else:
                print(f"存在合并失败的补丁文件，该模块不能创建MR")

    except Exception as e:
        return {"error": f"subprocess run时发生异常: {str(e)}"}
    finally:
        os.chdir(original_cwd)
        
    return results + result_failed

def create_mr(mr_server: str, project_url: str, project_token: str, src_branch: str, tar_branch: str, title: str, description: str) -> str:
    if mr_server == "sangfor":
        return create_sangfor_mr(project_url, project_token, src_branch, tar_branch, title, description)
    else: # default for gitee
        return create_gitee_mr(project_url, project_token, src_branch, tar_branch, title, description)

def create_sangfor_mr(project_url: str, project_token: str, src_branch: str, tar_branch: str, title: str, description: str) -> str:
    """创建深信服远程模块分支的merge request到远程该工程分支
    """
    try:
        mr_data = {
                "source_branch": src_branch,
                "target_branch": tar_branch,
                "title": title,
                "description": description,
                "assignee_id": 27, #固定
                "remove_source_branch": True #固定
        }
        headers = {'PRIVATE-TOKEN': project_token}
        response = requests.post(project_url, json=mr_data, headers=headers, timeout=10)
        response.raise_for_status()
        return f"成功创建MR: " + response.json()["web_url"]
    except requests.exceptions.RequestException as e:
        return f"推送失败: {str(e)}"
    except KeyError:
        return f"推送失败: 响应中缺少web_url字段，响应内容: {response.text}"

def create_gitee_mr(project_url: str, project_token: str, src_branch: str, tar_branch: str, title: str, description: str) -> str:
    """创建gitee远程模块分支的merge request到远程该工程分支
    """
    try:
        mr_data = {
               "title": title,
               "head": src_branch,
               "base": tar_branch,
               "body": description
        }
        headers = {
           "Authorization": f"token {project_token}",
           "Content-Type": "application/json"
        }
        response = requests.post(project_url, json=mr_data, headers=headers, timeout=10)
        response.raise_for_status()
        return f"成功创建MR: " + response.json()["html_url"]
    except requests.exceptions.RequestException as e:
        return f"推送失败: {str(e)}"
    except KeyError:
        return f"推送失败: 响应中缺少html_url字段，响应内容: {response.text}"

