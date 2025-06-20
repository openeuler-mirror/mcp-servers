import json
import os
import re
import logger
import shutil
import time
import urllib
from typing import Dict, List, Optional, Tuple, Any, Callable, Coroutine
from pathlib import Path

import random

from mcp.server.fastmcp import FastMCP
import requests
import git
from urllib.parse import urlparse, parse_qs
import subprocess
import curl_cffi

base_dir = "/root/cve_log"

mcp = FastMCP("openEuler kernel仓 CVE补丁查询与应用服务")
# 配置日志系统
logger = logger.getLogger(__name__)
logger.basicConfig(
    level=logger.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logger.StreamHandler(),
        logger.FileHandler(os.path.join(base_dir, "/server.log"), mode='a', encoding='utf-8')
    ]
)


def _get_cve_not_patch(patch_api_url: str = "", local_patch_path: Optional[str] = None) -> list[
                                                                                               str | Any] | None:
    """获取CVE补丁信息

    Args:
        cve_num: CVE编号
        cve_id: 可选的问题标题，用于补丁下载目录命名
        local_patch_path: 可选的本地补丁文件路径
    """

    try:
        # 优先从GitHub获取补丁
        # patch_api_url = f"https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num=CVE-2025-38005"
        logger.debug(f"patch_api_url patch_api_url = {patch_api_url}")
        response = requests.get(patch_api_url)
        response.raise_for_status()
        data = response.json()
        # 处理GitHub commit patch URL
        commit_urls = [item for item in data.get("body", []) if
                       isinstance(item, str) and item.endswith(".patch") == False and len(item) > 0]
        urlList = []
        deduplicationMap = {}
        commit_info = re.compile(page_info"<div class='commit-msg'>commit (?P<hash>.*?) upstream", re.S)
        for commit_url in commit_urls:
            proxies = {}
            page_info = curl_cffi.get(
                commit_url,
                headers={"X-Requested-With": "XMLHttpRequest"},
                verify=False,
                proxies=proxies)
            hashGorup = commit_info.search(page_info.text)
            # 获取重定向地址
            redirect_url = page_info.url
            # https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id=0ea0433f822ed0549715f7044c9cd1cf132ff7fa 获取0ea0433f822ed0549715f7044c9cd1cf132ff7fa前面的路径
            # 解析 URL
            parsed_url = urlparse(redirect_url)

            # 获取路径部分（即 ?id= 之前的部分）
            base_path = parsed_url.path

            if hashGorup != None:
                urlList.append(
                    parsed_url.scheme + "://" + parsed_url.hostname + base_path + "?id=" + hashGorup.group('hash'))
                if deduplicationMap.get(hashGorup.group('hash')):
                    continue
                deduplicationMap[hashGorup.group('hash')] = {
                    "commit_url": commit_url,
                    "patch_url": "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id=" + hashGorup.group(
                        'hash'),
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
        logger.warning(f"从https://git.kernel.org获取补丁失败: {str(e)}")
        return None


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
        logger.error(f"解析issue URL失败: {str(e)}")
        raise ValueError(f"无法解析issue URL: {str(e)}")
    repo_type = "src-openeuler" if org == "src-openeuler" else "openeuler"
    logger.debug(f"org :{org} repo :{repo} issue_id :{issue_id} repo_type :{repo_type}")
    # 从Gitee API获取issue描述
    try:
        issue_api_url = issue_url.replace("gitee.com", "gitee.com/api/v5/repos") + "?access_token=" + gitee_token
        logger.debug(f"issue_api_url {issue_api_url}")
        response = requests.get(issue_api_url)
        response.raise_for_status()
        issue_data = response.json()
        cve_id = issue_data['title']
        body_text = issue_data['body']
        version_start = body_text.find("漏洞归属的版本：") + len("漏洞归属的版本：")
        version_end = body_text.find("\n", version_start)
        version_str = body_text[version_start:version_end].strip()
        logger.debug(f"version_str = {version_str}")
        logger.debug(f"受影响版本信息：{version_str}")
    except Exception as e:
        logger.error(f"获取issue信息失败: {str(e)}")
        raise
    return {
        "issue_id": issue_id,
        "cve_id": cve_id,
        "org_name": org,
        "repo_name": repo,
        "repo_type": repo_type,
        "affected_versions": version_str,
        "issue_data": issue_data
    }


def get_commit_reference(commit_id, repo_path):
    # 判断目录是否存在
    if not os.path.exists(repo_path):
        # 获取上一层目录
        parent_dir = os.path.dirname(repo_path)
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


def generate_patch_header(commit_id, cve_id, bugzilla_url, patch_url, is_stable=False, repo_path=''):
    """生成符合规范的补丁头"""
    ref_version = get_commit_reference(commit_id, repo_path)

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
                logger.debug(f"仓库已存在且是git仓库: {local_path}")
                return local_path
            else:
                logger.debug(f"目录已存在但不是git仓库，删除后重新克隆: {local_path}")
                import shutil
                shutil.rmtree(local_path)

        logger.debug(f"Cloning repository to {local_path}")

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
        logger.debug(f"克隆操作结果: {result.stdout}")

        if not os.path.exists(local_path):
            raise RuntimeError(f"仓库克隆失败: {local_path}")

        return local_path

    except subprocess.CalledProcessError as e:
        logger.error(f"克隆命令执行失败: {str(e)}")
        raise RuntimeError(f"无法克隆仓库: {str(e)}")
    except Exception as e:
        logger.error(f"克隆操作失败: {str(e)}")
        raise RuntimeError(f"无法克隆仓库: {str(e)}")


def getUrlText(url):
    proxies = {}
    r = curl_cffi.get(
        url,
        headers={"X-Requested-With": "XMLHttpRequest"},
        verify=False,
        proxies=proxies)
    return r.text


def remove_leading_substring(s, substr):
    """移除字符串前面所有连续的指定子字符串"""
    if not s or not substr:
        return s
    substr_len = len(substr)
    while s.startswith(substr):
        s = s[substr_len:]
    return s


# @mcp.tool()
def apply_patch(
        fork_url: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = '/root/Image',
        patch_path:str="",
        signer_name:str="",
        signer_email:str="",
):
    """合并分支并且提交

    Args:
        fork_url: git仓库地址
        gitee_token: Gitee访问令牌(必须有仓库写入权限)
        branch_name: 处理的分支
        clone_dir: 本地克隆目录(默认为/tmp)
        patch_path: patch文件路径或者http地址
        signer_name:名称
        signer_email:邮箱

    Returns:
        是否合并提交成功
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
    if not os.path.exists(patch_path) and str(patch_path).find("http") != -1:
        text = getUrlText(patch_path)
        # 写入本地文件
        with open(clone_dir + "/commit_patch.patch", "w") as f:
            f.write(text)
        patch_path = clone_dir + "/commit_patch.patch"
    print('patch_path', patch_path)
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
        logger.error(f"切换分支失败: {str(e)}")
    fix_branch = branch_name
    try:
        # 执行 git am patch_path
        repo.git.apply(patch_path)
        logger.info("补丁成功应用")
    except git.exc.GitCommandError as e:
        logger.error(f"应用补丁失败: {str(e)}")

        # 检查是否处于 am 过程中的冲突状态
        if "Applying" in str(e):
            repo.git.am("--abort")
            return {
                "status": "error",
                "error": f"无法完成补丁应用，请检查冲突并重试。: {str(e)}"
            }
        else:
            repo.git.am("--abort")  # 非冲突错误，直接中止
            logger.info("已中止补丁应用过程")
            return {
                "status": "error",
                "error": f"无法应用补丁: {str(e)}"
            }

    # 生成commit message
    cve_id = os.path.basename(repo_path).replace('_', ' ')
    logger.info(f"补丁应用成功，issue标题: {cve_id}")

    # 添加所有变更并提交
    repo.git.add("--all")
    repo.git.commit("-m", patch_header, "-s", f"--author={signer_name} <{signer_email}>")

    # 推送变更到远程仓库
    try:
        logger.info(f"开始推送变更到远程仓库: {repo.remotes.origin.url}")
        repo.git.push("origin", fix_branch)
        logger.info("变更推送成功")
    except Exception as e:
        try:
            repo.git.push("origin --set-upstream", fix_branch)
        except Exception as e:
            try:
                repo.git.push("origin", fix_branch, "--force")
            except Exception as e:
                logger.error(f"推送变更失败: {str(e)}")
                return {
                    "status": "error",
                    "error": f"无法推送变更: {str(e)}"
                }

    # # 使用新方法处理补丁
    logger.info(branch_name)
    logger.info(fix_branch)

    # 等5秒执行一次
    time.sleep(2)
    logger.info(f"当前分支:{org_name},{branch_name},{fix_branch}")

    # 清理临时文件
    if repo_path != patch_path and os.path.exists(patch_path):
        logger.debug(f"清理临时补丁文件: {patch_path}")
        os.remove(patch_path)
        logger.debug("临时文件清理完成")
    logger.info({
        "status": "success",
        "repo_path": repo_path,
        "hash": hash
    })
    return {
        "status": "success",
        "repo_path": repo_path,
        "hash": hash
    }


def merge_branch_to_commit_check(
        fork_url: str,
        hash: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = '/root/Image',
        patch_url: str = "",
):
    if patch_url is None or patch_url == "":
        patch_url = f'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id={hash}'

    text = getUrlText(patch_url)
    with open(clone_dir + f"/commit_patch_{hash}.patch", "w") as f:
        f.write(text)
    patch_path = clone_dir + f"/commit_patch_{hash}.patch"
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
        logger.error(f"切换分支失败: {str(e)}")
    # 配置用户信息
    logger.debug("配置Git用户信息")
    fix_branch = branch_name
    # 执行git am patch_path

    try:
        # 执行 git am patch_path
        repo.git.apply("--check", patch_path)
        logger.info("补丁检测成功")
        return {
            "status": "success",
            "repo_path": repo_path,
            "patch_path": patch_path,
            "hash": hash
        }
    except git.exc.GitCommandError as e:
        return {
            "status": "error",
            "repo_path": repo_path,
            "patch_path": patch_path,
            "error": hash
        }


def merge_branch_to_cmmoit_new(
        fork_url: str,
        hash: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = '/root/Image',
        cve_id: str = "",
        issue_url="",
        signer_name="",
        signer_email="",
        patch_url="",
        commit_url="",
        is_push=False
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
        logger.error(f"切换分支失败: {str(e)}")
    # 配置用户信息
    logger.debug("配置Git用户信息")
    repo.git.config("user.name", signer_name)
    repo.git.config("user.email", signer_email)
    fix_branch = branch_name
    # 执行git am patch_path
    try:
        # 执行 git am patch_path
        repo.git.am(patch_path)
        logger.info("补丁成功应用")
    except git.exc.GitCommandError as e:
        logger.error(f"应用补丁失败: {str(e)}")

        # 检查是否处于 am 过程中的冲突状态
        if "Applying" in str(e):
            repo.git.am("--abort")
            raise RuntimeError("无法完成补丁应用，请检查冲突并重试。")
        else:
            repo.git.am("--abort")  # 非冲突错误，直接中止
            logger.info("已中止补丁应用过程")
            raise RuntimeError(f"无法应用补丁: {str(e)}")

    # 获取补丁头
    patch_header = generate_patch_header(hash, cve_id, issue_url, commit_url, is_stable=False,
                                         repo_path=(clone_dir + "\\kernel_commit_query"))

    # 生成commit message
    cve_id = os.path.basename(repo_path).replace('_', ' ')
    logger.info(f"补丁应用成功，issue标题: {cve_id}")

    # 添加所有变更并提交
    repo.git.add("--all")
    repo.git.commit("-m", patch_header, "-s", f"--author={signer_name} <{signer_email}>")
    if is_push:
        # 推送变更到远程仓库
        try:
            logger.info(f"开始推送变更到远程仓库: {repo.remotes.origin.url}")
            repo.git.push("origin", fix_branch)
            logger.info("变更推送成功")
        except Exception as e:
            try:
                repo.git.push("origin --set-upstream", fix_branch)
            except Exception as e:
                logger.error(f"推送变更失败: {str(e)}")
                raise RuntimeError(f"无法推送变更: {str(e)}")

    # # 使用新方法处理补丁
    logger.info(branch_name)
    logger.info(fix_branch)

    # 等5秒执行一次
    time.sleep(2)
    logger.info(f"当前分支:{org_name},{branch_name},{fix_branch}")

    # 清理临时文件
    if repo_path != patch_path and os.path.exists(patch_path):
        logger.debug(f"清理临时补丁文件: {patch_path}")
        os.remove(patch_path)
        logger.debug("临时文件清理完成")
    logger.info({
        "status": "success",
        "repo_path": repo_path,
        "hash": hash
    })
    return {
        "status": "success",
        "repo_path": repo_path,
        "hash": hash
    }


def get_merge_branch_by_cve_patchs(
        fork_url: str,
        issue_url: str,
        gitee_token: str,
        branch_name: str,
        clone_dir: str = '/root/Image'
):
    try:
        issue_info = _parse_gitee_issue_url(issue_url, gitee_token)
        cve_title = issue_info["cve_id"]
        patch_url = 'https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num=' + cve_title
    except Exception as e:
        patch_url = issue_url
    # 解析URL
    parsed_url = urlparse(patch_url)

    # 获取查询参数
    query_params = parse_qs(parsed_url.query)

    # 输出结果

    cve_title = query_params.get('cve_num')[0]
    logger.debug(f"cvetitle = {cve_title} {patch_url}")
    patch_contents = _get_cve_not_patch(patch_url)
    if not patch_contents:
        logger.error(f"无法获取CVE补丁内容: {cve_title}")
        return False
    index = 1
    list = []
    for patch_content in patch_contents:
        try:
            item = merge_branch_to_commit_check(
                fork_url,
                patch_content.get("hash"),
                gitee_token,
                branch_name,
                clone_dir,
                patch_content.get("patch_url"),
            )
            list.append(item)
        except Exception as e:
            logger.warning(f"操作失败: {str(e)}")
        index += 1
    return list


def merge_branch_by_cve_new(
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
        cve_title = issue_info["cve_id"]
        patch_url = 'https://api.openeuler.org/cve-manager/v1/cve/detail/patch?cve_num=' + cve_title
    except Exception as e:
        patch_url = issue_url
    # 解析URL
    parsed_url = urlparse(patch_url)

    # 获取查询参数
    query_params = parse_qs(parsed_url.query)

    cve_title = query_params.get('cve_num')[0]
    logger.debug(f"cvetitle = {cve_title} {patch_url}")
    patch_contents = _get_cve_not_patch(patch_url)
    if not patch_contents:
        logger.error(f"无法获取CVE补丁内容: {cve_title}")
        return False
    index = 1
    for patch_content in patch_contents:
        try:
            merge_branch_to_cmmoit_new(fork_url,
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
                                       index == len(patch_contents)
                                       )
        except Exception as e:
            logger.warning(f"操作失败: {str(e)}")
        index += 1
    return True


@mcp.tool()
def get_issue_analyse_branch_table(issue_url: str,
                                   repo_url: str,
                                   gitee_token: str,
                                   clone_dir: str = '/root/Image',
                                   branchList: list = [
                                       'OLK-5.10',
                                       'OLK-6.6',
                                       'master',
                                   ],
                                   signer_name:str ="",
                                   signer_email:str ="",
                                   patch_header:str ="合并",
                                   pr_url:str = "https://gitee.com/api/v5/repos/lipingEmmasiguyi/kernel/pulls"
                                   ):
    """查询issue和分支合并冲突结果

    Args:
        issue_url: gitee issue URL (必须包含CVE编号)
        repo_url: git仓库地址
        gitee_token: Gitee访问令牌(必须有仓库写入权限)
        clone_dir: 本地克隆目录(默认为/tmp)
        branchList: 分支列表

    Returns:
        冲突结果表格json结构
    """
    table = []
    # 获取issue的仓库地址
    issueInfo = _parse_gitee_issue_url(issue_url, gitee_token)
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
    issueTitle = issueInfo.get("cve_id")
    # 指纹浏览器 https://lore.kernel.org/linux-cve-announce/?q=issueTitle
    fingerprint_url = f"https://lore.kernel.org/linux-cve-announce/"
    fingerprint_text = getUrlText(f"{fingerprint_url}?q={issueTitle}")
    href_obj = re.compile(f".*?<pre>1.*?<b><a.*?href=\"(?P<href>.*?)\">{issueInfo['cve_id']}.*?", re.S)
    href_text_obj = re.compile(
        ".*?Affected and fixed versions.*?===========================(?P<href_text>.*?)Please see <a", re.S)
    commit_obj = re.compile(".*?in(?P<version>.*?)with.*?commit(?P<commit>.*?)", re.S)
    hrefRes = href_obj.search(fingerprint_text)
    introducedCommitList = []
    fixedCommitList = []
    commitVersion = {}
    if hrefRes != None:
        href = hrefRes.group("href")
        href_text = getUrlText(f"{fingerprint_url}{href}")
        commitListStr = href_text_obj.search(href_text)
        if commitListStr != None:
            commitListStr = commitListStr.group("href_text").strip()
            commitList = commitListStr.split("\n")
            for commit in commitList:
                commitIntroducedAndFixedAndList = remove_leading_substring(commit.strip(), "Issue ").split("and")
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
    # 获取当前活动分支
    repo = git.Repo(repo_path)
    index = 1
    for branch in branchList:
        # 切换分支
        try:
            repo.git.checkout(branch)
        except Exception as e:
            try:
                repo.git.checkout('-b', branch, f'origin/{branch}')
            except Exception as e:
                logger.error(f"切换分支失败: {str(e)}")
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
                    logger.info(f"搜索commit成功:{branch} {commit_id}")
            except Exception as e:
                logger.error(f"搜索commit失败:{branch} {str(e)}")
        for commit_id in fixedCommitList:
            try:
                if repo.git.log(commit_id, oneline=True):
                    fixedCommitStatus = True
                    commit_id_index = commit_id
                    logger.info(f"搜索commit成功:{branch} {commit_id}")
            except Exception as e:
                logger.error(f"搜索commit失败:{branch} {str(e)}")
        version = ""
        if commitVersion.get(commit_id_index):
            version = f"({commitVersion[commit_id_index]})"
        maocheck = {}
        if fixedCommitStatus:
            patchs = get_merge_branch_by_cve_patchs(repo_url, issue_url, gitee_token, branch, clone_dir)
            for patch in patchs:
                if patch['status'] == 'success':
                    if maocheck.get(patch['patch_path']+""+branch) == None:
                        maocheck[patch['patch_path']+""+branch] = 1
                        apply_patch(repo_url,gitee_token,branch,clone_dir, patch['patch_path'],signer_name,signer_email,patch_header)
                    table.append({
                        "补丁ID": issueInfo["issue_id"],
                        "目标分支": branch,
                        "是否受影响": "受影响",
                        "适配状态": "成功",
                        "冲突点": patch['patch_path'],
                        "建议调整文件": "N/A",
                    })
                    continue
                # 获取路径里面的文件名
                table.append({
                    "补丁ID": issueInfo["issue_id"],
                    "目标分支": branch,
                    "是否受影响": "受影响",
                    "适配状态": "需要调整",
                    "冲突点": patch['patch_path'],
                    "建议调整文件": "",
                })
            logger.info(f"{branch} 存在漏洞的commit:{commit_id_index} 漏洞的版本:{version}\n")
            index += 1
            continue
        if introducedCommitStatus:
            # git apply --check path/to/patch.patch 检查是否冲突
            patchs = get_merge_branch_by_cve_patchs(repo_url, issue_url, gitee_token, branch, clone_dir)
            for patch in patchs:
                if patch['status'] == 'success':
                    if maocheck.get(patch['patch_path']+""+branch) == None:
                        maocheck[patch['patch_path']+""+branch] = 1
                        apply_patch(repo_url,gitee_token,branch,clone_dir, patch['patch_path'],signer_name,signer_email,patch_header)
                    table.append({
                        "补丁ID": issueInfo["issue_id"],
                        "目标分支": branch,
                        "是否受影响": "受影响",
                        "适配状态": "成功",
                        "冲突点": patch['patch_path'],
                        "建议调整文件": "N/A",
                    })
                    continue
                # 获取路径里面的文件名
                table.append({
                    "补丁ID": issueInfo["issue_id"],
                    "目标分支": branch,
                    "是否受影响": "受影响",
                    "适配状态": "需要调整",
                    "冲突点": patch['patch_path'],
                    "建议调整文件": "",
                })
            logger.info(f"{branch} 存在漏洞的commit:{commit_id_index} 漏洞的版本:{version}\n")
            index += 1
            continue
        table.append({
            "补丁ID": issueInfo["issue_id"],
            "目标分支": branch,
            "是否受影响": "不受影响",
            "适配状态": "",
            "冲突点": "已修复",
            "建议调整文件": "N/A",
        })
        logger.info(f"{branch} 不存在漏洞")
        index += 1
        continue
    # 获取 "/repos/中间字符串/pulls"

    # table = list(set(table))
    for item in table:
        if item.get("适配状态") == "成功":
            prText = ""
            # 创建PR到上游仓库
            try:
                repo_url = repo_url.replace('https://gitee.com/', '')
                branch = item.get('目标分支')
                logger.info(f"开始创建PR到上游仓库{repo_url}:{branch}")
                jsonObj = {
                    "title": f"Fix {issueInfo['cve_id']}",
                    "head": f"{repo_url}:{branch}",
                    "base": f"{branch}",
                    "body": f"{issue_url}"
                }
                logger.info(jsonObj)
                pr_result = requests.post(
                    pr_url,
                    headers={"Authorization": f"token {gitee_token}"},
                    json=jsonObj
                )
                # 获取pr_result status = 400 的body内容
                prText = pr_result.text
                pr_result.raise_for_status()
                item['pr提交结果'] = "提交pr成功"
            except Exception as e:
                logger.error(f"创建PR失败: {str(e)}")
                item['pr提交结果'] = prText

    return table


if __name__ == "__main__":
    mcp.run(transport='stdio')
    # result = get_issue_analyse_branch_table(
    #     "https://gitee.com/lipingEmmaSiguyi/kernel_1/issues/ICN353",
    #     "https://gitee.com/lzx20000118/kernel",
    #     "11dc2eca2967bc550d95734f903d9d5b",
    #     "/root/Image",
    #     [
    #         'OLK-6.6',
    #     ],
    #     "suyibk",
    #     "suyibk@qq.com"
    # )

    # print(result)
    #
    # 'OLK-5.10',
    # 'OLK-6.6',
    # 'master',
    # result = [
    #     {
    #         "补丁ID": "CVE-2025-38005",
    #         "目标分支": "OLK-6.6",
    #         "冲突点": "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id=f83ac8d30c43fd902af7c84c480f216157b60ef0",
    #     }
    # ]
    # print(result)
    # for item in result:
    #     apply_patch(
    #         "https://gitee.com/lzx20000118/kernel",
    #         "11dc2eca2967bc550d95734f903d9d5b",
    #         item.get("目标分支"),
    #         "/root/Image",
    #         item.get("冲突点"),
    #         "test",
    #         "test@qq.com",
    #         "测试"
    #     )