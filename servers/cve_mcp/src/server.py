import json
import os
import re
import logging
import shutil
import time
import urllib
from typing import Dict, List, Optional, Tuple, Any, Callable, Coroutine
from pathlib import Path

import random

from fastmcp.prompts import Prompt
from mcp import GetPromptResult
from mcp.server.fastmcp.prompts.base import AssistantMessage, UserMessage, Message

base_dir = "/tmp/cve_log"

# 配置日志系统
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(base_dir, "/server.log"), mode='a', encoding='utf-8')
    ]
)
import requests
import git
from mcp.server.fastmcp import FastMCP
from urllib.parse import urlparse, parse_qs
import subprocess
import curl_cffi

#path = r'C:\Users\suyib\AppData\Local\Google\Chrome\Application\chrome.exe'

mcp = FastMCP("openEuler CVE补丁查询与应用服务")


# 作用：解析 Gitee Issue 地址并提取组织名、仓库名、Issue ID 等信息。
# 参数：
# issue_url: Gitee Issue 地址。
# gitee_token: 可选的 Gitee 访问令牌。
# 返回值：包含 Issue 基本信息的字典（如 org_name, repo_name, issue_id, affected_versions）。
def _parse_gitee_issue_url(issue_url: str, gitee_token: Optional[str] = None) -> Dict[str, str]:
    """解析gitee issue URL并获取基本信息"""
    try:
        pattern = r"https://gitee.com/([^/]+)/([^/]+)/issues/([^/]+)"
        match = re.match(pattern, issue_url)
        if not match:
            raise ValueError("无效的gitee issue URL格式")
        org = match.group(1)
        repo = match.group(2)
        issue_id = match.group(3)
    except Exception as e:
        logging.error(f"解析issue URL失败: {str(e)}")
        raise ValueError(f"无法解析issue URL: {str(e)}")
    repo_type = "src-openeuler" if org == "src-openeuler" else "openeuler"
    logging.debug(f"org :{org} repo :{repo} issue_id :{issue_id} repo_type :{repo_type}")
    # 从Gitee API获取issue描述
    try:
        issue_api_url = issue_url.replace("gitee.com", "gitee.com/api/v5/repos") + "?access_token=" + gitee_token
        logging.debug(f"issue_api_url {issue_api_url}")
        response = requests.get(issue_api_url)
        response.raise_for_status()
        issue_data = response.json()
        print("_parse_gitee_issue_url",issue_data)
        issue_title = issue_data['title']
        body_text = issue_data['body']
        version_start = body_text.find("漏洞归属的版本：") + len("漏洞归属的版本：")
        version_end = body_text.find("\n", version_start)
        version_str = body_text[version_start:version_end].strip()
        logging.debug(f"version_str = {version_str}")
        logging.debug(f"受影响版本信息：{version_str}")
    except Exception as e:
        logging.error(f"获取issue信息失败: {str(e)}")
        raise
    return {
        "issue_id": issue_id,
        "issue_title": issue_title,
        "org_name": org,
        "repo_name": repo,
        "repo_type": repo_type,
        "affected_versions": version_str,
        "issue_data": issue_data
    }


# 作用：优先从 GitHub 获取补丁，若失败则尝试使用本地补丁文件。
# 参数：
# cve_num: CVE 编号。
# issue_title: 问题标题。
# local_patch_path: 本地补丁路径。
# 返回值：成功返回补丁文本内容，否则返回 None。
def _get_cve_patch(cve_num: str, issue_title: Optional[str] = None, local_patch_path: Optional[str] = None) -> Optional[
    str]:
    """获取CVE补丁信息
    
    Args:
        cve_num: CVE编号
        issue_title: 可选的问题标题，用于补丁下载目录命名
        local_patch_path: 可选的本地补丁文件路径
    """
    try:
        # 优先从GitHub获取补丁
        patch_api_url = f"https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num={issue_title}"
        logging.debug(f"patch_api_url patch_api_url = {patch_api_url}")
        response = requests.get(patch_api_url)
        response.raise_for_status()
        data = response.json()
        # 处理GitHub commit patch URL
        patch_urls = [item for item in data.get("body", []) if isinstance(item, str) and item.endswith(".patch")]

        if patch_urls:
            logging.info(f"找到补丁URL: {patch_urls[0]}")
            patch_response = requests.get(patch_urls[0])
            patch_response.raise_for_status()
            return patch_response.text

        logging.warning("未找到有效的补丁URL")

        # 回退到原始API方式
        if data.get("patch_content"):
            return data["patch_content"]

    except Exception as e:
        logging.warning(f"从GitHub获取补丁失败: {str(e)}")
        if local_patch_path and os.path.exists(local_patch_path):
            logging.info(f"尝试使用本地补丁文件: {local_patch_path}")
            try:
                with open(local_patch_path, 'r') as f:
                    return f.read()
            except Exception as read_error:
                logging.error(f"读取本地补丁文件失败: {str(read_error)}")
        return None


def getUrlText(url):
    proxies = {}
    r = curl_cffi.get(
        url,
        headers={"X-Requested-With": "XMLHttpRequest"},
    verify = False,
    proxies = proxies)
    return r.text


def _get_cve_not_patch(patch_api_url: str = "", local_patch_path: Optional[str] = None) -> list[
                                                                                                         str | Any] | None:
    """获取CVE补丁信息

    Args:
        cve_num: CVE编号
        issue_title: 可选的问题标题，用于补丁下载目录命名
        local_patch_path: 可选的本地补丁文件路径
    """

    try:
        # 优先从GitHub获取补丁
        # patch_api_url = f"https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num=CVE-2025-38005"
        logging.debug(f"patch_api_url patch_api_url = {patch_api_url}")
        response = requests.get(patch_api_url)
        response.raise_for_status()
        data = response.json()
        # 处理GitHub commit patch URL
        commit_urls = [item for item in data.get("body", []) if
                      isinstance(item, str) and item.endswith(".patch") == False and len(item) > 0]
        urlList = []
        deduplicationMap = {}
        tbody = re.compile(r"<div class='commit-msg'>commit (?P<hash>.*?) upstream", re.S)
        for commit_url in commit_urls:
            proxies = {}
            r = curl_cffi.get(
                commit_url,
                headers={"X-Requested-With": "XMLHttpRequest"},
                verify=False,
                proxies=proxies)
            hashGorup = tbody.search(r.text)
            # 获取重定向地址
            redirect_url = r.url
            # https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id=0ea0433f822ed0549715f7044c9cd1cf132ff7fa 获取0ea0433f822ed0549715f7044c9cd1cf132ff7fa前面的路径
            # 解析 URL
            parsed_url = urlparse(redirect_url)

            # 获取路径部分（即 ?id= 之前的部分）
            base_path = parsed_url.path
            print(commit_url,redirect_url)

            if hashGorup != None:
                urlList.append(
                    parsed_url.scheme + "://" + parsed_url.hostname + base_path + "?id=" + hashGorup.group('hash'))
                if deduplicationMap.get(hashGorup.group('hash')):
                     continue
                deduplicationMap[hashGorup.group('hash')] = {
                    "commit_url":commit_url,
                    "patch_url":"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id=" + hashGorup.group('hash'),
                    "hash": hashGorup.group('hash')
                }
        patchList = []
        for deduplicationKey in deduplicationMap:
            patchUrl = deduplicationMap[deduplicationKey]
            text = getUrlText(patchUrl.get("patch_url"))
            patchList.append({
                "commit_url": patchUrl.get("commit_url"),
                "patch_url": patchUrl.get("patch_url"),
                "hash": patchUrl.get("hash"),
                "text": text,
            })
        print("patchList--end")

        return patchList

    except Exception as e:
        logging.warning(f"从https://git.kernel.org获取补丁失败: {str(e)}")
        return None


# 作用：克隆 Gitee 仓库到指定目录。
# 支持 HTTPS + Token 认证。
# 返回值：本地仓库路径。
def _clone_repository(
        org_name: str,
        repo_name: str,
        clone_dir: str,
        gitee_token: str = None
) -> str:
    """克隆Gitee仓库到本地"""
    local_path = os.path.join(clone_dir, repo_name)

    try:
        # 检查目录是否已存在且是git仓库
        if os.path.exists(local_path):
            if os.path.exists(os.path.join(local_path, '.git')):
                logging.debug(f"仓库已存在且是git仓库: {local_path}")
                return local_path
            else:
                logging.debug(f"目录已存在但不是git仓库，删除后重新克隆: {local_path}")
                import shutil
                shutil.rmtree(local_path)

        logging.debug(f"Cloning repository to {local_path}")

        # 使用HTTPS方式克隆，支持token认证
        if gitee_token:
            clone_url = f"https://oauth2:{gitee_token}@gitee.com/{org_name}/{repo_name}.git"
        else:
            clone_url = f"https://gitee.com/{org_name}/{repo_name}.git"

        result = subprocess.run(
            ["git", "clone", clone_url, local_path],
            check=True,
            cwd=clone_dir,
            capture_output=True,
            text=True
        )
        logging.debug(f"克隆操作结果: {result.stdout}")

        if not os.path.exists(local_path):
            raise RuntimeError(f"仓库克隆失败: {local_path}")

        return local_path

    except subprocess.CalledProcessError as e:
        logging.error(f"克隆命令执行失败: {str(e)}")
        raise RuntimeError(f"无法克隆仓库: {str(e)}")
    except Exception as e:
        logging.error(f"克隆操作失败: {str(e)}")
        raise RuntimeError(f"无法克隆仓库: {str(e)}")


#
def _ask_user_for_repo_info() -> tuple:
    """询问用户获取仓库信息"""
    import click

    # 获取仓库URL
    repo_url = click.prompt("请输入仓库的完整URL")
    # 从URL中解析org和repo
    parts = repo_url.strip().rstrip('/').split('/')
    org_name = parts[-2]
    repo_name = parts[-1].replace('.git', '')
    return (org_name, repo_name)


# 作用：在 RPM spec 文件中插入新的 PatchXXXX: 条目。
# 实现方式：
# 查找已有的 Patch 行。
# 插入新行（自增编号）。
def _modify_spec_file(repo_path: str, patch_name: str, repo, version_section) -> None:
    """修改spec文件增加Patch条目
    
    Args:
        repo_path: 仓库路径
        patch_name: 补丁文件名
    """
    try:
        # 查找spec文件
        spec_files = [f for f in os.listdir(repo_path) if f.endswith('.spec')]
        if not spec_files:
            raise FileNotFoundError("未找到spec文件")

        spec_path = os.path.join(repo_path, spec_files[0])
        logging.info(f"找到spec文件: {spec_path}")

        # 读取spec内容
        with open(spec_path, 'r') as f:
            lines = f.readlines()

        # 查找Patch部分
        patch_section = -1
        changelog_section = -1
        version_section_old = ""
        for i, line in enumerate(lines):
            if line.startswith('Patch'):
                patch_num = int(line.split(':')[0][5:])
                patch_section = max(patch_section, patch_num)
            if line.startswith('changelog'):
                changelog_section = 1
            if line.startswith('Version'):
                version_section_old = line.split(':')[1].strip()
            elif line.startswith('%patch') and patch_section == -1:
                patch_section = 0

        if patch_section == -1:
            patch_section = 0

        # 添加新Patch条目
        new_patch_num = patch_section + 1
        new_patch_line = f"Patch{new_patch_num:04d}:      {patch_name}\n"
        # "Sun Sep 29 2024 yaoxin <yao xin001@hoperun.com>- 1.7.0-2" 获取时间 和 git名称和gti邮箱
        patch_time = time.strftime("%a %b %d %Y %H:%M:%S %z")
        username = repo.git.execute(['git', 'config', '--get', 'user.name'])
        email = repo.git.execute(['git', 'config', '--get', 'user.email'])
        if version_section_old:
            oldList = version_section_old.split('-')
            if len(oldList) > 1 and oldList[0] == version_section:
                version_section = oldList[0] + "-" + (int(oldList[len(oldList) - 1]) + 1)
            else:
                version_section += "-1"

        new_changelog_line = f"changelog:      {patch_time} {username} <{email}>- {version_section}\n"

        # 插入到第一个Patch行之前或文件末尾
        inserted = False
        for i, line in enumerate(lines):
            if line.startswith('Patch'):
                lines.insert(i, new_patch_line)
                inserted = True
                break
            if line.startswith('changelog'):
                lines.insert(i, new_changelog_line)
                inserted = True
                break

        if not inserted:
            lines.append(new_patch_line)

        # 写回文件
        with open(spec_path, 'w') as f:
            f.writelines(lines)

        logging.info(f"成功添加Patch条目: {new_patch_line.strip()}")

    except Exception as e:
        logging.error(f"修改spec文件失败: {str(e)}")
        raise RuntimeError(f"无法修改spec文件: {str(e)}")


# 作用：自动递增 spec 文件中的 Release 字段。
# 示例：Release: 1%{?dist} → Release: 2%{?dist}
def _increment_release(repo_path: str) -> None:
    """增加release号
    
    Args:
        repo_path: 仓库路径
    """
    try:
        # 查找spec文件
        spec_files = [f for f in os.listdir(repo_path) if f.endswith('.spec')]
        if not spec_files:
            raise FileNotFoundError("未找到spec文件")

        spec_path = os.path.join(repo_path, spec_files[0])
        logging.info(f"找到spec文件: {spec_path}")

        # 读取spec内容
        with open(spec_path, 'r') as f:
            lines = f.readlines()

        # 查找Release行
        for i, line in enumerate(lines):
            if line.startswith('Release:'):
                parts = line.split(':')
                if len(parts) < 2:
                    continue

                release_part = parts[1].strip()
                # 提取数字部分
                release_num = 1
                num_match = re.search(r'\d+', release_part)
                if num_match:
                    release_num = int(num_match.group()) + 1

                # 替换Release行
                new_release = f"Release:        {release_num}%{{?dist}}\n"
                lines[i] = new_release
                logging.info(f"更新Release号为: {release_num}")
                break

        # 写回文件
        with open(spec_path, 'w') as f:
            f.writelines(lines)

    except Exception as e:
        logging.error(f"增加release号失败: {str(e)}")
        raise RuntimeError(f"无法增加release号: {str(e)}")


# 作用：在 %changelog 部分新增一行变更记录。
def _add_changelog(repo_path: str, cve_id: str) -> None:
    """新增changelog条目
    
    Args:
        repo_path: 仓库路径
        cve_id: CVE编号
    """
    try:
        # 查找spec文件
        spec_files = [f for f in os.listdir(repo_path) if f.endswith('.spec')]
        if not spec_files:
            raise FileNotFoundError("未找到spec文件")

        spec_path = os.path.join(repo_path, spec_files[0])
        logging.info(f"找到spec文件: {spec_path}")

        # 读取spec内容
        with open(spec_path, 'r') as f:
            lines = f.readlines()

        # 查找%changelog部分
        changelog_start = -1
        for i, line in enumerate(lines):
            if line.startswith('%changelog'):
                changelog_start = i
                break

        if changelog_start == -1:
            lines.append('\n%changelog\n')
            changelog_start = len(lines) - 1

        # 获取当前日期
        from datetime import datetime
        now = datetime.now()
        date_str = now.strftime('%a %b %d %Y')

        # 创建新changelog条目
        new_entry = f"""* {date_str} yaoxin <yao_xin001@hoperun.com> - 1.7.0-2
- Fix {cve_id}
"""

        # 插入到changelog部分开始处
        lines.insert(changelog_start + 1, new_entry)

        # 写回文件
        with open(spec_path, 'w') as f:
            f.writelines(lines)

        logging.info(f"成功添加changelog条目")

    except Exception as e:
        logging.error(f"添加changelog失败: {str(e)}")
        raise RuntimeError(f"无法添加changelog: {str(e)}")


# 作用：拷贝补丁文件到仓库，修改 spec 文件，提交 Git 变更，并推送至远程仓库。
# 涉及操作：
# 拷贝补丁文件。
# 调用 _modify_spec_file、_increment_release、_add_changelog。
# Git add/commit/push。
# 返回值：(patch_file, repo_path)，用于缓存。
def _apply_patch(repo_path: str, patch_path: str, version_section, fix_branch) -> bool:
    """应用补丁(兼容旧方法)
    
    Args:
        repo_path: 仓库路径
        patch_path: 补丁路径
        
    Returns:
        bool: 是否成功
    """
    try:
        _, _ = _apply_patch2(repo_path, patch_path, None, version_section, fix_branch)
        return True
    except Exception:
        # logging.error("应用补丁失败")
        # exit()
        return False




def _get_version_from_spec(repo_path: str) -> Optional[str]:
    """从spec文件读取Version字段"""
    try:
        spec_files = [f for f in os.listdir(repo_path) if f.endswith('.spec')]
        if not spec_files:
            return None

        spec_path = os.path.join(repo_path, spec_files[0])
        with open(spec_path, 'r') as f:
            for line in f:
                if line.startswith('Version:'):
                    return line.split(':')[1].strip()
        return None
    except Exception as e:
        logging.error(f"读取spec文件版本失败: {str(e)}")
        return None


def _get_branch_version(repo_path: str, branch_name: str, repo_name: str) -> Optional[str]:
    try:
        repo = git.Repo(repo_path)

        # 特殊处理kernel仓库
        if repo_name == "kernel":
            # 1. 扫描所有远程分支
            logging.info("开始扫描远程分支版本对应关系:")
            for ref in repo.remote().refs:
                if ref.name == 'HEAD':
                    continue
                branch = ref.name.split('/')[-1]
                commit = repo.commit(ref)
                version_match = re.search(r"release (\d+\.\d+\.\d+)", commit.message)
                version_str = version_match.group(1) if version_match else "N/A"
                logging.info(f"分支 {branch}: {version_str}")
                if branch == branch_name and version_match:
                    return version_match.group(1)

            # 2. 扫描所有LTS标签
            logging.info("开始扫描LTS标签版本对应关系:")
            for tag in repo.tags:
                if 'LTS' in tag.name:
                    commit = repo.commit(tag)
                    version_match = re.search(r"release (\d+\.\d+\.\d+)", commit.message)
                    version_str = version_match.group(1) if version_match else "N/A"
                    logging.info(f"标签 {tag.name}: {version_str}")
                    if tag.name == branch_name and version_match:
                        return version_match.group(1)

            # 3. 回退到分支名匹配
            version_match = re.search(r"(\d+\.\d+\.\d+)", branch_name)
            if version_match:
                logging.info(f"回退到分支名匹配: {version_match.group(1)}")
                return version_match.group(1)
        else:
            # 非kernel仓库从spec文件读取版本
            return _get_version_from_spec(repo_path)

        logging.info(f"分支/标签 '{branch_name}' 未找到版本号信息")
        return None

    except Exception as e:
        logging.error(f"获取分支版本失败: {str(e)}", exc_info=True)
        return None


def _clone_repository_with_patch(
        org_name: str = None,
        repo_name: str = None,
        clone_dir: str = None,
        patch_path: str = None,
        timeout: int = 30,
        affected_versions: List[str] = None,
        gitee_token: str = None
) -> Dict[str, str]:
    """克隆Gitee仓库到本地并处理补丁
    """
    try:
        # 强制要求提供仓库信息
        if org_name is None or repo_name is None:
            raise ValueError("必须提供org_name和repo_name参数")

        logging.info(f"开始处理本地仓库: {org_name}/{repo_name}")
        repo_path = os.path.join(clone_dir, repo_name)
        if not os.path.exists(repo_path):
            raise FileNotFoundError(f"本地仓库不存在: {repo_path}")

        # 检查补丁文件是否存在
        if not os.path.exists(patch_path):
            raise FileNotFoundError(f"补丁文件不存在: {patch_path}")

        results = {}
        branchList = []
        if affected_versions:
            repo = git.Repo(repo_path)

            branches = []
            # 远程分支
            logging.info("开始扫描远程分支...")
            for ref in repo.remote().refs:
                branch_name = ref.name.split('/')[-1]
                if branch_name != 'HEAD':
                    branches.append(branch_name)
                    logging.debug(f"找到远程分支: {branch_name}")

            # 标签
            logging.info("开始扫描标签...")
            for tag in repo.tags:
                branches.append(tag.name)
                logging.debug(f"找到标签: {tag.name}")

            logging.info(f"共找到 {len(branches)} 个分支/标签需要检查")
            logging.info("分支/标签与版本匹配关系:")
            # 处理每个分支/标签
            for branch in branches:
                logging.info(f"正在处理分支/标签: {branch}")
                # 获取版本号
                branch_version = _get_branch_version(repo_path, branch, repo_name)
                if not branch_version:
                    logging.info(f"分支/标签 '{branch}' 未提取到版本号，跳过处理")
                    continue

                logging.info(f"分支/标签 '{branch}' 版本信息 - 提取版本: {branch_version}")
                logging.info(f"受影响版本列表: {affected_versions}")

                # 详细输出版本匹配情况
                if branch_version in affected_versions:
                    logging.info(f"√ 匹配: 分支/标签 '{branch}' (版本 {branch_version}) 匹配目标版本")
                else:
                    logging.info(f"× 不匹配: 分支/标签 '{branch}' (版本 {branch_version}) 不在目标版本列表中")

                # 检查版本是否在受影响范围内
                if branch_version in affected_versions:
                    logging.info(f"处理受影响分支/标签: {branch} (版本: {branch_version} 匹配)")

                    # 切换到分支/标签
                    try:
                        if branch in repo.tags:
                            repo.git.checkout(f"tags/{branch}")
                        else:
                            repo.git.checkout(branch)

                        # 创建修复分支
                        fix_branch = f"cve-fix/{branch}"
                        try:
                            repo.git.checkout('-b', fix_branch)
                        except Exception as e:
                            repo.git.checkout(fix_branch)

                        # 应用补丁
                        try:
                            _apply_patch(repo_path, patch_path, affected_versions, fix_branch)
                            results[branch] = "补丁应用成功"
                        except Exception as e:
                            results[branch] = f"补丁应用失败: {str(e)}"
                            logging.error(f"分支 {branch} 补丁应用失败: {str(e)}")
                        branchList.append({
                            "branch": branch,
                            "fix_branch": fix_branch
                        })
                    except Exception as e:
                        results[branch] = f"分支切换失败: {str(e)}"
                        logging.error(f"无法切换到分支 {branch}: {str(e)}")
                else:
                    logging.debug(f"分支/标签 '{branch}' 版本 {branch_version} 不在受影响版本列表中")

        # 获取所有远程分支信息
        repo = git.Repo(repo_path)
        remote_branches = []
        for ref in repo.remote().refs:
            if ref.name != 'HEAD':
                branch_name = ref.name.split('/')[-1]
                commit = repo.commit(ref)
                version = _get_branch_version(repo_path, branch_name, "")
                remote_branches.append({
                    "name": branch_name,
                    "version": version,
                    "commit": str(commit),
                    "message": commit.message.strip()
                })

        return {
            "repo_path": repo_path,
            "branches": remote_branches,
            "patch_results": results,
            "branchList": branchList
        }

    except Exception as e:
        logging.error(f"仓库操作失败: {str(e)}")
        raise RuntimeError(f"无法完成仓库操作: {str(e)}")


# 缓存字典
_patch_cache = {}
_patch_arr_cache = {}
_repo_cache = {}


def _apply_patch2(repo_path: str, patch_file: str, cve_id: str = None, version_section="", fix_branch="") -> Tuple[
    str, str]:
    """应用补丁并提交变更
    
    Args:
        repo_path: 本地仓库路径
        patch_file: 本地补丁文件路径
        cve_id: 可选的CVE编号，用于changelog
        
    Returns:
        tuple: (patch_file_path, repo_path) 缓存路径
    """
    try:
        logging.info(f"开始处理补丁应用: repo={repo_path}, patch={patch_file}")

        # 缓存仓库路径
        repo_name = os.path.basename(repo_path)
        if repo_name in _repo_cache:
            logging.debug(f"仓库路径已缓存: {repo_name} -> {_repo_cache[repo_name]}")
        else:
            logging.debug(f"缓存新仓库路径: {repo_name} -> {repo_path}")
            _repo_cache[repo_name] = repo_path

        # 检查补丁文件是否存在
        if not os.path.exists(patch_file):
            # 尝试使用标准补丁文件名
            standard_patch = os.path.join(os.path.dirname(patch_file), "patch.patch")
            if os.path.exists(standard_patch):
                patch_file = standard_patch
            else:
                raise ValueError(f"本地补丁文件不存在: {patch_file}。请确保提供有效的本地补丁路径")

        logging.info(f"使用补丁文件: {patch_file}")

        # 初始化Git仓库
        logging.debug(f"初始化Git仓库: {repo_path}")
        repo = git.Repo(repo_path)
        os.chdir(repo_path)

        # 拷贝patch文件到仓库
        patch_name = os.path.basename(patch_file)
        dest_patch = os.path.join(repo_path, patch_name)
        logging.debug(f"patch_name {patch_name} dest_patch {dest_patch}")
        shutil.copy2(patch_file, dest_patch)
        logging.info(f"已拷贝patch文件到: {dest_patch}")

        # 修改spec文件
        _modify_spec_file(repo_path, patch_name, repo, version_section)
        _increment_release(repo_path)
        if cve_id:
            _add_changelog(repo_path, cve_id)

        # 配置用户信息
        logging.debug("配置Git用户信息")
        repo.git.config("user.name", "test")
        repo.git.config("user.email", "cve-bot@example.com")

        # 生成commit message
        issue_title = os.path.basename(repo_path).replace('_', ' ')
        logging.info(f"补丁应用成功，issue标题: {issue_title}")

        # 添加所有变更并提交
        repo.git.add("--all")
        repo.git.commit("-m", f"Fix {cve_id}: {issue_title}")

        # 推送变更到远程仓库
        try:
            logging.info(f"开始推送变更到远程仓库: {repo.remotes.origin.url}")
            repo.git.push("origin", fix_branch)
            logging.info("变更推送成功")
        except Exception as e:
            try:
                repo.git.push("origin --set-upstream", fix_branch)
            except Exception as e:
                logging.error(f"推送变更失败: {str(e)}")
                raise RuntimeError(f"无法推送变更: {str(e)}")

        logging.info(f"补丁处理完成，返回缓存路径: patch={patch_file}, repo={repo_path}")
        return (patch_file, repo_path)

    except Exception as e:
        logging.error(f"补丁应用过程中发生异常，错误详情:\n{str(e)}", exc_info=True)
        raise RuntimeError(f"无法应用补丁: {str(e)}")


from mcp.server.fastmcp.prompts.base import AssistantMessage, UserMessage, Message
import json

@mcp.prompt()
def invalid_params(message: str,instructions: str,required_params = []) -> list[Message]:
    return [
        UserMessage(message),
        UserMessage(instructions),
        # 数组转json字符串
        AssistantMessage(json.dumps(required_params))
    ]
@mcp.prompt()
def patch_fetch_failed(message: str, instructions: str, fallback_action: dict) -> list[Message]:
    """
    当自动获取补丁失败时调用，提示用户手动提供补丁信息

    Args:
        message: 错误消息
        instructions: 操作指南
        fallback_action: 是否调用内核解析

    Returns:
        包含用户提示和指令的消息列表
    """
    return [
        UserMessage(f"❌ {message}"),
        UserMessage(instructions),
    ]


@mcp.prompt()
def patch_not_found(message: str, instructions: str, required_params: list = []) -> list[Message]:
    """
    当未找到有效补丁文件时调用，引导用户上传或指定补丁

    Args:
        message: 错误消息
        instructions: 操作指南
        required_params: 需要用户提供的参数列表

    Returns:
        包含用户提示和指令的消息列表
    """
    return [
        UserMessage(f"⚠️ {message}"),
        UserMessage(instructions),
        AssistantMessage(json.dumps(required_params)),
        AssistantMessage("请上传补丁文件或提供补丁URL："),
        AssistantMessage("""
        操作步骤：
        1. 点击下方"上传文件"按钮选择本地补丁文件
        2. 或直接输入补丁文件的URL
        """),
        AssistantMessage("支持的补丁格式：.patch, .diff, .txt")
    ]


@mcp.prompt()
def fork_required(message: str, instructions: str, next_action: dict, source_repo: str, validation: dict = None) -> \
list[Message]:
    """
    当需要用户Fork仓库时调用，引导用户完成Fork操作并提供Fork后的URL

    Args:
        message: 提示消息
        instructions: 操作指南
        next_action: 下一步要调用的工具及其参数
        source_repo: 源仓库URL
        validation: 输入验证规则

    Returns:
        包含用户提示和指令的消息列表
    """
    return [
        UserMessage(f"🔗 {message}"),
        UserMessage(instructions),
        AssistantMessage(json.dumps({
            "next_action": next_action,
            "source_repo": source_repo,
            "validation": validation
        })),
        AssistantMessage(f"请访问源仓库：{source_repo}"),
        AssistantMessage("""
        操作步骤：
        1. 点击页面右上角的"Fork"按钮
        2. 选择您的命名空间并确认Fork
        3. Fork完成后，复制新仓库的URL（以https://gitee.com/开头）
        4. 在此处粘贴Fork后的仓库URL
        """),
        AssistantMessage("验证规则：输入必须是有效的Gitee仓库URL")
    ]
# 作用：完整处理一个 CVE Issue，包括：
# 解析 Issue URL。
# 获取补丁。
# 提示用户 Fork 上游仓库。
# 返回值：包含下一步操作的信息（如需提供 fork 后的仓库地址）。
@mcp.tool()
async def process_cve_issue(  # noqa: C901
        issue_url: str,
        gitee_token: str,
        clone_dir: str = "/tmp",
        pr_title: str = None,
        pr_body: str = None,
        local_patch_path: str = None,
        repo_type: str = "src-openeuler"
) -> GetPromptResult:
    """完整处理CVE issue流程
    
    Args:
        issue_url: gitee issue URL (必须包含CVE编号)
        gitee_token: Gitee访问令牌(必须有仓库写入权限)
        clone_dir: 本地克隆目录(默认为/tmp)
        
    Returns:
        MCP交互提示，指导用户完成后续操作
    """
    # 参数验证
    if not issue_url or issue_url=='' or not gitee_token or gitee_token=='':
        return await mcp.get_prompt("invalid_params",{
            "message": "缺少必要参数",
            "instructions": "请提供有效的issue_url和gitee_token",
            "required_params": ["issue_url", "gitee_token"]
        })
    issue_info = {}
    try:
        issue_info = _parse_gitee_issue_url(issue_url, gitee_token)
        cve_num = None
        cve_title = issue_info["issue_title"]
        
        # 尝试获取补丁
        patch_content = _get_cve_patch(cve_num, cve_title)
        if patch_content:
            local_patch_path = os.path.join(clone_dir, f"{issue_info['repo_name']}-{cve_title}.patch")
            with open(local_patch_path, "w") as f:
                f.write(patch_content)
            _patch_cache[issue_info["issue_title"]] = local_patch_path
    except Exception as e:
        logging.warning(f"自动获取补丁失败: {str(e)}")
        res = await mcp.get_prompt("patch_fetch_failed",{
            "message": "自动获取补丁失败",
            "instructions": f"请手动提供补丁文件路径或检查网络连接\n错误详情: {str(e)}",
            "fallback_action": {
                "tool": "process_cve_issue_not_patch",
                "params": {
                    "issue_url": issue_url,
                    "gitee_token": gitee_token
                }
            }
        })
        return res

    # 检查补丁文件
    if not local_patch_path or not os.path.exists(local_patch_path):
        return await mcp.get_prompt("patch_not_found",{
            "message": "未找到有效补丁文件",
            "instructions": f"请提供有效的补丁文件路径",
            "required_params": ["local_patch_path"]
        })

    # 显示源码仓信息并提示用户fork
    source_repo_url = f"https://gitee.com/{issue_info['repo_type']}/{issue_info['repo_name']}"
    return await mcp.get_prompt("fork_required",{
        "message": f"请先fork以下仓库: {source_repo_url}",
        "instructions": "操作步骤:\n1. 点击上方链接访问仓库\n2. 点击右上角'Fork'按钮\n3. 完成后提供fork后的仓库URL",
        "next_action": {
            "tool": "continue_cve_processing",
            "params": {
                "issue_url": issue_url,
                "gitee_token": gitee_token,
                "local_patch_path": local_patch_path
            }
        },
        "source_repo": source_repo_url,
        "validation": {
            "type": "url",
            "pattern": r"https://gitee.com/[^/]+/[^/]+"
        }
    })


# 作用：接收用户 Fork 后的仓库地址，继续执行以下步骤：
# 克隆仓库。
# 应用补丁。
# 提交 PR 到上游仓库。
# 返回值：PR 创建结果信息
@mcp.tool()
def continue_cve_processing(
        fork_url: str,
        issue_url: str,
        gitee_token: str,
        clone_dir: str = '/tmp',
        local_patch_path: str = None
) -> dict:
    # 如果没有提供local_patch_path，尝试从全局缓存获取
    if local_patch_path is None:
        issue_info = _parse_gitee_issue_url(issue_url, gitee_token)
        cve_match = re.search(r'CVE-\d{4}-\d+', issue_info['issue_title'])
        if cve_match:
            cve_num = cve_match.group(0)
            local_patch_path = _patch_cache.get(cve_num)
    """继续处理用户fork后的仓库
    
    Args:
        fork_url: 用户fork后的仓库URL
        issue_url: 原始issue URL
        gitee_token: Gitee访问令牌
        clone_dir: 本地克隆目录
        local_patch_path: 本地补丁路径
        
    Returns:
        处理结果字典
    """
    # 解析fork URL获取组织名和仓库名
    parts = fork_url.strip().rstrip('/').split('/')
    org_name = parts[-2]
    repo_name = parts[-1].replace('.git', '')

    # 克隆用户fork的仓库
    repo_path = _clone_repository(
        org_name=org_name,
        repo_name=repo_name,
        clone_dir=clone_dir,
        gitee_token=gitee_token
    )
    # 解析issue URL获取受影响版本
    issue_info = _parse_gitee_issue_url(issue_url, gitee_token)
    print(issue_info)
    affected_versions = []
    if issue_info['affected_versions']:
        affected_versions = issue_info['affected_versions']
    patch_path_value = ""
    if issue_info['issue_title'] in _patch_cache:
        patch_path_value = _patch_cache[issue_info['issue_title']]
    else:
        print(_patch_cache)
    # # 使用新方法处理补丁
    result = _clone_repository_with_patch(
        org_name=org_name,
        repo_name=repo_name,
        clone_dir=clone_dir,
        patch_path=patch_path_value,
        affected_versions=affected_versions,
        gitee_token=gitee_token
    )

    # 获取当前活动分支
    repo = git.Repo(repo_path)
    current_branch = repo.active_branch.name
    _apply_patch(repo_path, _patch_cache[issue_info['issue_title']], affected_versions, current_branch)
    patch_file = local_patch_path
    logging.info(result['branchList'])
    resultSuccessReturns = []
    resultErrorReturns = []
    for branchObj in result['branchList']:
        branch = branchObj.get("branch")
        fix_branch = branchObj.get("fix_branch")
        # 等5秒执行一次
        time.sleep(2)
        logging.info(f"当前分支:{org_name},{branch},{fix_branch}")
        # 创建PR到上游仓库
        try:
            logging.info("开始创建PR到上游仓库")
            jsonObj = {
                "title": f"Fix {issue_info['issue_id']}",
                "head": f"{org_name}/{repo_name}:{fix_branch}",
                "base": f"{branch}",
                "body": f"Applied security patch for {issue_info['issue_id']}\n\n受影响版本: {', '.join(affected_versions)}"
            }
            logging.info(jsonObj)
            pr_result = requests.post(
                f"https://gitee.com/api/v5/repos/{issue_info['org_name']}/{issue_info['repo_name']}/pulls",
                headers={"Authorization": f"token {gitee_token}"},
                json=jsonObj
            )
            pr_result.raise_for_status()
            logging.info(pr_result.text)
            pr_data = pr_result.json()
            resultSuccessReturns.append({
                "status": "补丁应用并提交PR成功",
                "repo_path": repo_path,
                "patch_path": patch_file,
                "pr_url": pr_data["html_url"],
                "pr_number": pr_data["number"]
            })

        except Exception as e:
            logging.error(f"创建PR失败: {str(e)}")
            resultErrorReturns.append({
                "status": f"补丁应用成功但PR创建失败: {str(e)}",
                "repo_path": repo_path,
                "patch_path": patch_file,
                "pr_url": None,
                "pr_number": None
            })

    # 清理临时文件
    if repo_path != patch_file and os.path.exists(patch_file):
        logging.debug(f"清理临时补丁文件: {patch_file}")
        os.remove(patch_file)
        logging.debug("临时文件清理完成")
    logging.info({
        "status": "success",
        "results": resultSuccessReturns,
        "message": f"成功处理 {len(resultSuccessReturns)} 个分支的PR创建",
        "error": f"失败处理 {len(resultErrorReturns)} 个分支的PR创建",
        "error_results": resultErrorReturns,
        "repo_path": repo_path,
        "issue_id": issue_info['issue_id']
    })
    return {
        "status": "success",
        "results": resultSuccessReturns,
        "message": f"成功处理 {len(resultSuccessReturns)} 个分支的PR创建",
        "error": f"失败处理 {len(resultErrorReturns)} 个分支的PR创建",
        "error_results": resultErrorReturns,
        "repo_path": repo_path,
        "issue_id": issue_info['issue_id']
    }


# 作用：通过 Gitee API 创建 PR。
# 参数：
# org_name, repo_name: 上游仓库信息。
# head_branch: 源分支（格式：fork_org:branch）。
# title, body: PR 标题和描述。
# 返回值：Gitee 返回的 PR 数据。
@mcp.tool()
def _create_pr(
        org_name: str,
        repo_name: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
        gitee_token: str
) -> dict:
    """创建PR到上游仓库
    
    Args:
        org_name: 上游组织名
        repo_name: 上游仓库名
        head_branch: 源分支(格式: fork_org:branch)
        base_branch: 目标分支(格式: branch)
        title: PR标题
        body: PR描述
        gitee_token: Gitee访问令牌
        
    Returns:
        PR创建结果字典
    """
    try:
        jsonObj = {
            "title": title,
            "head": f"{org_name}/{repo_name}:{head_branch}",
            "base": f"{base_branch}",
            "body": body
        }
        logging.info(jsonObj)
        response = requests.post(
            f"https://gitee.com/api/v5/repos/{org_name}/{repo_name}/pulls",
            headers={"Authorization": f"token {gitee_token}"},
            json=jsonObj
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"PR创建请求失败: {str(e)}")
        raise RuntimeError(f"无法创建PR: {str(e)}")


@mcp.tool()
def process_cve_issue_not_patch(  # noqa: C901
        issue_url: str,
        gitee_token: str,
        clone_dir: str = "/root/Image",
) -> list[str | Any] | None:
    """完整处理CVE issue流程

    Args:
        issue_url: gitee issue URL
        gitee_token: Gitee访问令牌
        clone_dir: 本地克隆目录(默认为/tmp)

    Returns:
        包含所有操作结果的字典
    """
    # 解析URL
    parsed_url = urlparse(issue_url)

    # 获取查询参数
    query_params = parse_qs(parsed_url.query)

    # 输出结果
    print(query_params)

    cve_title = query_params.get('cve_num')[0]
    logging.debug(f"cvetitle = aaaaaaa {cve_title}")
    try:
        patch_contents = _get_cve_not_patch(issue_url)
        patch_contents_file = []
        index = 1
        for patch_content in patch_contents:
            local_patch_path = os.path.join(clone_dir, f"kernel-{index}.patch")
            with open(local_patch_path, "w") as f:
                f.write(patch_content.get('text'))
            logging.info(f"自动下载补丁成功，保存到: {local_patch_path}")
            patch_contents_file.append(local_patch_path)
            index += 1
            _patch_cache[patch_content.get('hash')] = local_patch_path
        return patch_contents
    except Exception as e:
        logging.warning(f"自动下载补丁失败: {str(e)}")
    return None

def get_commit_reference( commit_id, repo_path):
    # 判断目录是否存在
    if not os.path.exists(repo_path):
        # 获取上一层目录
        parent_dir = os.path.dirname(repo_path)
        print(parent_dir,repo_path)
        result = subprocess.run(
            ["git", "clone", "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git", repo_path],
            check=True,
            cwd=parent_dir,
            capture_output=True,
            text=True
        )
        if not os.path.exists(repo_path):
            raise RuntimeError(f"仓库克隆失败: {repo_path}")

    repo = git.Repo(repo_path)
    subprocess.run(
        ["git", "pull"],
        check=True,
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    """获取提交的引用信息，如mainline版本或stable版本"""
    try:
        name_rev = repo.git.name_rev(commit_id)
        # 解析name_rev输出，格式通常为: <commit-hash> tags/<tag-name>~<number>
        match = re.search(r'tags/([^~]+)', name_rev)
        if match:
            tag_name = match.group(1)
            return tag_name
        return "unknown"
    except Exception as e:
        print(f"获取提交引用失败: {e}")
        return "unknown"

def generate_patch_header(commit_id, cve_id, bugzilla_url, patch_url, is_stable=False,repo_path=''):
    """生成符合规范的补丁头"""
    ref_version = get_commit_reference(commit_id,repo_path)

    inclusion_type = "stable inclusion" if is_stable else "mainline inclusion"
    from_line = f"from mainline-{ref_version}" if not is_stable else f"from stable-{ref_version}"

    header = f"""
        {inclusion_type}
        {from_line}
        commit id: {commit_id}
        bugzilla: {bugzilla_url}
        CVE: {cve_id}
        Reference: {patch_url}
        """
    return header
@mcp.tool()
def merge_branch_by_cve(
        fork_url: str,
        issue_url: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = '/root/Image',
        signer_name: str = None,
        signer_email: str = None,
):
    try:
        issue_info = _parse_gitee_issue_url(issue_url, gitee_token)
        cve_title = issue_info["issue_title"]
        patch_url = 'https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num='+cve_title
    except Exception as e:
        patch_url = issue_url
    # 解析URL
    parsed_url = urlparse(patch_url)

    # 获取查询参数
    query_params = parse_qs(parsed_url.query)

    # 输出结果
    print(query_params)

    cve_title = query_params.get('cve_num')[0]
    logging.debug(f"cvetitle = aaaaaaa {cve_title} {patch_url}")
    patch_contents = _get_cve_not_patch(patch_url)
    index = 1
    for patch_content in patch_contents:
        try:
            merge_branch_to_cmmoit(fork_url,
                                   patch_content.get("hash"),
                                   gitee_token,
                                   branch_name,
                                   clone_dir,
                                   cve_title,
                                   issue_url,
                                   signer_name,
                                   signer_email,
                                   patch_content.get("patch_url"),
                                   patch_content.get("commit_url"),
                                   index==len(patch_contents)
                                   )
        except Exception as e:
            logging.warning(f"操作失败: {str(e)}")
        index+=1
    return True

@mcp.tool()
def merge_branch_to_cmmoit(
        fork_url: str,
        hash: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = '/root/Image',
        cve_id: str = "",
        issue_url="",
        signer_name = "",
        signer_email = "",
        patch_url = "",
        commit_url = "",
        is_push = False
):
    if patch_url is None or patch_url == "":
        patch_url = f'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id={hash}'

    text = getUrlText(patch_url)
    with open(clone_dir + "\\commit_patch.patch", "w") as f:
        f.write(text)
    patch_path = clone_dir + "\\commit_patch.patch"
    """继续处理用户fork后的仓库

    Args:
        fork_url: 用户fork后的仓库URL
        issue_url: 原始issue URL
        gitee_token: Gitee访问令牌
        clone_dir: 本地克隆目录
        local_patch_path: 本地补丁路径

    Returns:
        处理结果字典
    """
    # 解析fork URL获取组织名和仓库名
    parts = fork_url.strip().rstrip('/').split('/')
    org_name = parts[-2]
    repo_name = parts[-1].replace('.git', '')
    repo_path = clone_dir + "/" + repo_name
    if not os.path.exists(clone_dir + "/" + repo_name):
        # 克隆用户fork的仓库
        repo_path = _clone_repository(
            org_name=org_name,
            repo_name=repo_name,
            clone_dir=clone_dir,
            gitee_token=gitee_token
        )

    # 获取当前活动分支
    repo = git.Repo(repo_path)
    # 获取所有本地分支名称
    branches = repo.git.branch().split()
    try:
        # 检查目标分支是否存在
        if branch_name in branches:
            # 如果分支已存在，则切换到该分支
            repo.git.checkout(branch_name)
        else:
            repo.git.checkout('-b', branch_name)
    except Exception as e:
        logging.error(f"切换分支失败: {str(e)}")
    # 配置用户信息
    logging.debug("配置Git用户信息")
    repo.git.config("user.name", signer_name)
    repo.git.config("user.email", signer_email)
    fix_branch = branch_name
    # 执行git am patch_path
    try:
        # 执行 git am patch_path
        repo.git.am(patch_path)
        logging.info("补丁成功应用")
    except git.exc.GitCommandError as e:
        logging.error(f"应用补丁失败: {str(e)}")

        # 检查是否处于 am 过程中的冲突状态
        if "Applying" in str(e):
            repo.git.am("--abort")
            raise RuntimeError("无法完成补丁应用，请检查冲突并重试。")
        else:
            repo.git.am("--abort")  # 非冲突错误，直接中止
            logging.info("已中止补丁应用过程")
            raise RuntimeError(f"无法应用补丁: {str(e)}")

    # 获取补丁头
    patch_header = generate_patch_header(hash, cve_id, issue_url, commit_url, is_stable=False,repo_path=(clone_dir+"\\kernel_commit_query"))


    # 生成commit message
    issue_title = os.path.basename(repo_path).replace('_', ' ')
    logging.info(f"补丁应用成功，issue标题: {issue_title}")

    # 添加所有变更并提交
    repo.git.add("--all")
    repo.git.commit("-m", patch_header, "-s", f"--author={signer_name} <{signer_email}>")
    if is_push:
        # 推送变更到远程仓库
        try:
            logging.info(f"开始推送变更到远程仓库: {repo.remotes.origin.url}")
            repo.git.push("origin", fix_branch)
            logging.info("变更推送成功")
        except Exception as e:
            try:
                repo.git.push("origin --set-upstream", fix_branch)
            except Exception as e:
                logging.error(f"推送变更失败: {str(e)}")
                raise RuntimeError(f"无法推送变更: {str(e)}")

    # # 使用新方法处理补丁
    logging.info(branch_name)
    logging.info(fix_branch)

    # 等5秒执行一次
    time.sleep(2)
    logging.info(f"当前分支:{org_name},{branch_name},{fix_branch}")

    # 清理临时文件
    if repo_path != patch_path and os.path.exists(patch_path):
        logging.debug(f"清理临时补丁文件: {patch_path}")
        os.remove(patch_path)
        logging.debug("临时文件清理完成")
    logging.info({
        "status": "success",
        "repo_path": repo_path,
        "hash": hash
    })
    return {
        "status": "success",
        "repo_path": repo_path,
        "hash": hash
    }
def remove_leading_substring(s, substr):
    """移除字符串前面所有连续的指定子字符串"""
    if not s or not substr:
        return s
    substr_len = len(substr)
    while s.startswith(substr):
        s = s[substr_len:]
    return s
@mcp.tool()
def issue_comments(issue_url: str,
                   repo_url:str,
                   gitee_token: str,
                   clone_dir: str = '/tmp',
                   branchList: list = [
                       'openEuler-22.03-LTS-SP3',
                       'openEuler-22.03-LTS-SP4',
                       'openEuler-24.03-LTS-SP1',
                       'openEuler-24.03-LTS-SP2',
                       'openEuler-24.03-LTS-SP2',
                       'master',
                       'openEuler-20.03-LTS-SP4',
                       'openEuler-24.03-LTS-Next',
                   ],
                    signer_name:str = "",
                    signer_email:str = "",
                   ):
    # 获取issue的仓库地址
    # https://gitee.com/lipingEmmaSiguyi/kernel_1/issues/ICIFJ2
    issueInfo = _parse_gitee_issue_url(issue_url, gitee_token)
    # https://gitee.com/lzx20000118/kernel
    parts = repo_url.strip().rstrip('/').split('/')
    org_name = parts[-2]
    repo_name = parts[-1].replace('.git', '')
    repo_path = clone_dir + "/" + repo_name
    # clone仓库下来
    if not os.path.exists(repo_path):
        # 克隆用户fork的仓库
        repo_path = _clone_repository(
            org_name=org_name,
            repo_name=repo_name,
            clone_dir=clone_dir,
            gitee_token=gitee_token
        )

    org_name = issueInfo.get("org_name")
    repo_name = issueInfo.get("repo_name")
    issueTitle = issueInfo.get("issue_title")
    # 指纹浏览器 https://lore.kernel.org/linux-cve-announce/?q=issueTitle
    fingerprint_url = f"https://lore.kernel.org/linux-cve-announce/"
    fingerprint_text = getUrlText(f"{fingerprint_url}?q={issueTitle}")
    href_obj = re.compile(f".*?<pre>1.*?<b><a.*?href=\"(?P<href>.*?)\">{issueInfo['issue_title']}.*?", re.S)
    href_text_obj = re.compile(
        ".*?Affected and fixed versions.*?===========================(?P<href_text>.*?)Please see <a", re.S)
    commit_obj = re.compile(".*?in(?P<version>.*?)with.*?commit(?P<commit>.*?)", re.S)
    hrefRes = href_obj.search(fingerprint_text)
    introducedCommitList = []
    fixedCommitList = []
    commitVersion = {}
    comments = ""
    if hrefRes != None:
        href = hrefRes.group("href")
        print('hrefgroup', href)
        href_text = getUrlText(f"{fingerprint_url}{href}")
        commitListStr = href_text_obj.search(href_text)
        if commitListStr != None:
            commitListStr = commitListStr.group("href_text").strip()
            commitList = commitListStr.split("\n")
            print('commitList', commitList)
            for commit in commitList:
                # "Issue introduced in 5.6 with commit 25dcb5dd7b7ce5587c1df18f584ff78f51a68a94 and fixed in 5.10.238 with commit 27e71fa08711e09d81e06a54007b362a5426fd22" 获取第一个commit id
                commitIntroducedAndFixedAndList = remove_leading_substring(commit, "Issue ").split("and")
                commitIntroducedAndFixeds = []
                for commitIntroducedAndFixedAnd in commitIntroducedAndFixedAndList:
                    commitIntroducedAndFixeds.append(commitIntroducedAndFixedAnd.strip().split(" "))
                for commitIntroducedAndFixed in commitIntroducedAndFixeds:
                    commit_id = commitIntroducedAndFixed[5]
                    version = commitIntroducedAndFixed[2]
                    commitVersion[commit_id] = version
                    if commitIntroducedAndFixed[0] == 'introduced':
                        introducedCommitList.append(commit_id)
                    elif commitIntroducedAndFixed[0] == 'fixed':
                        fixedCommitList.append(commit_id)
    print('introducedCommitList', introducedCommitList)
    print('fixedCommitList', fixedCommitList)
    print('commitVersion', commitVersion)
    # 获取当前活动分支
    repo = git.Repo(repo_path)
    index = 1
    for branch in branchList:
        # 切换分支
        try:
            repo.git.checkout(branch)
        except Exception as e:
            try:
                repo.git.checkout('-b', branch,f'origin/{branch}')
            except Exception as e:
                logging.error(f"切换分支失败: {str(e)}")
                continue
        introducedCommitStatus = False
        fixedCommitStatus = False
        commit_id_index = ''
        # 搜索该分支git log 是否存在漏洞的commit
        for commit_id in introducedCommitList:
            try:
                if repo.git.log(commit_id, oneline=True):
                    introducedCommitStatus = True
                    commit_id_index = commit_id
            except Exception as e:
                logging.error(f"搜索commit失败:{branch} {str(e)}")
        for commit_id in fixedCommitList:
            try:
                if repo.git.log(commit_id, oneline=True):
                    fixedCommitStatus = True
                    commit_id_index = commit_id
            except Exception as e:
                logging.error(f"搜索commit失败:{branch} {str(e)}")
        version = ""
        if commitVersion.get(commit_id_index):
            version = f"({commitVersion[commit_id_index]})"
        if fixedCommitStatus:
            comments += f"{index} {branch}{version}:已修复\r\n"
            logging.info(f"{branch} 存在漏洞的commit:{commit_id_index} 漏洞的版本:{version}\n")
            index += 1
            continue
        if introducedCommitStatus:
            comments += f"{index} {branch}{version}:受影响\r\n"
            logging.info(f"{branch} 存在漏洞的commit:{commit_id_index} 漏洞的版本:{version}\n")
            index += 1
            merge_branch_by_cve(repo_url,issue_url,gitee_token,branch,clone_dir,signer_name,signer_email)
            continue
        comments += f"{index} {branch}{version}:不受影响\r\n"
        logging.info(f"{branch} 不存在漏洞")
        index += 1
        continue

    print(comments)
    if comments == "":
        logging.error(f"评论内容为空")
        return False
    # 提交评论到issue
    # https://gitee.com/api/v5/repos/{owner}/{repo}/issues/{number}/comments
    response = requests.post(
        f"https://gitee.com/api/v5/repos/{org_name}/{repo_name}/issues/{issueInfo['issue_id']}/comments",
        json={
            "access_token": gitee_token,
            "body": comments
        }
    )
    response.raise_for_status()
    jsonRes = response.json()
    if jsonRes and jsonRes.get("id") != None:
        logging.info("评论成功")
        return True
    logging.error(f"评论失败:{response.text}")
    return False

if __name__ == "__main__":
    # mcp.run()
    issue_comments(
        "https://gitee.com/lipingEmmaSiguyi/kernel_1/issues/ICIFIQ",
        "https://gitee.com/lzx20000118/kernel",
        "11dc2eca2967bc550d95734f903d9d5b",
        "/root/Image"
    )