import subprocess
import json
import argparse
import logging
from typing import Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP
import os

dir = os.path.dirname(__file__)
os.environ['PYTHONPATH'] = dir

from cvekit.utils.locales import i18n, update_docstring

mcp = FastMCP(i18n("CVE修复流程自动化工具，提供CVE分析、补丁适配等功能"))

# 配置参数解析
parser = argparse.ArgumentParser()
parser.add_argument('--gitee-token', help=i18n('Gitee访问令牌'))
args, _ = parser.parse_known_args()


@update_docstring(i18n("""执行cvekit命令并返回结果"""))
def run_cvekit(action: str, params: dict) -> dict:
    try:
        env = os.environ.copy()
        # 构建基础命令
        cmd = ['/home/dev/exit/envs/camel_env/bin/python','-m','cvekit.cli',f'--action={action}']
        if action != 'setup-env':
            cmd.append('--json')
        
        # 添加公共参数
        if 'cve_id' in params and params["cve_id"]:
            cmd.append(f'--cve-id={params["cve_id"]}')
        if args.gitee_token:
            cmd.append(f'--gitee-token={args.gitee_token}')
        elif 'gitee_token' in params:
            cmd.append(f'--gitee-token={params["gitee_token"]}')
        
        # 添加动作特定参数
        if action == 'setup-env':
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')
                
        elif action == 'analyze-branches':
            if 'branches' in params:
                cmd.append(f'--branches={params["branches"]}')
            if 'signer_name' in params:
                cmd.append(f'--signer-name={params["signer_name"]}')
            if 'signer_email' in params:
                cmd.append(f'--signer-email={params["signer_email"]}')
        
        elif action == 'apply-patch':
            if 'patch_path' in params:
                cmd.append(f'--patch-path={params["patch_path"]}')
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
            if 'branch' in params:
                cmd.append(f'--branch={params["branch"]}')
            if 'signer_name' in params:
                cmd.append(f'--signer-name={params["signer_name"]}')
            if 'signer_email' in params:
                cmd.append(f'--signer-email={params["signer_email"]}')

        elif action == 'create-pr':
            if 'branch' in params:
                cmd.append(f'--branch={params["branch"]}')
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
            if 'repo_url' in params:
                cmd.append(f'--repo-url={params["repo_url"]}')

        result = subprocess.run(
            cmd,
            check=True,
            env = env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        return json.loads(result.stdout)

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logging.error(i18n("cvekit执行失败: %s") % (str(error_msg)))
        return {"error": error_msg, "command": " ".join(cmd)}
    except json.JSONDecodeError:
        logging.error(i18n("cvekit输出非JSON格式"))
        return {"error": "Invalid JSON output", "output": result.stdout}

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第一步：
        通过调用gitee的api，解析gitee issue URL并获取基本信息
        在这里将通过issue_url解析得到的issue_info以json格式反馈给用户
        主要告知用户我们获取的issue_id, cve_id, org_name, repo_name, affected_versions这些是否正确
    """))
def parse_issue(
    cve_id: str = Field(..., description="cve id"),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    
    result = run_cvekit('parse-issue', {
        'cve_id': cve_id,
        'gitee_token': gitee_token
    })
    
    if 'error' in result:
        return i18n("解析Issue失败: %s") % (result['error'])
    
    data = result.get('data', {})
    res = i18n("已解析Issue: %s\n") % (data.get('issue_id', ''))
    res += f"- CVE ID: {data.get('cve_id', '')}\n"
    res += f"- Issue URL: {data.get('issue_url', '')}\n"
    res += i18n("- 组织: %s\n") % (data.get('org_name', ''))
    res += i18n("- 仓库: %s\n") % (data.get('repo_name', ''))
    res += i18n("- 受影响版本: %s\n") % (data.get('affected_versions', ''))
    # res += i18n("请确认以上信息是否正确")
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第二步：
        设置仓库环境，克隆官方仓库，添加fork远程
    """))
def setup_env(
    fork_repo_url: str = Field(..., description=i18n("Fork仓库URL")),
    clone_dir: str = Field(..., description=i18n("工作空间或克隆目录，本地克隆仓库在该目录所在的仓库名文件夹中")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> dict:

    run_cvekit('setup-env', {
        'fork_repo_url': fork_repo_url,
        'clone_dir': clone_dir,
        'gitee_token': gitee_token
    })

    return i18n("仓库已经下载到%s路径下") % (clone_dir)

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第三步：
        获取漏洞相关的真实上游提交信息，并将获取到的commit告知给用户
    """))
def get_commits(
    cve_id: str = Field(..., description="cve id"),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    result = run_cvekit('get-commits', {
        'cve_id': cve_id,
        'gitee_token': gitee_token
    })
    
    # Check for errors first
    if 'error' in result:
        return i18n("获取提交信息失败: %s") % (result['error'])
    
    res = i18n("已获取CVE %s的提交信息:\n") % (result.get('cve_id', ''))
    res += i18n("- 引入漏洞的提交: %s\n") % (result.get('introduced', ''))
    res += i18n("- 修复漏洞的提交: %s\n") % (result.get('fixed', ''))
    # res += i18n("请确认以上提交信息是否正确")
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第四步：
        分析introduced_commit在本地仓库的哪些分支被引入，如果引入的话，是否被fixed了，以此来分析哪些分支需要应用补丁
        并检查从上游获取的补丁直接应用，是否存在冲突
        该步骤中的参数branches为kernel的分支名，和issue分析中的受影响版本并不一致，若用户未输入要分析的分支名，使用默认值即可
    """))
def analyze_branches(
    cve_id: str = Field(..., description="cve id"),
    branches: Optional[str] = Field('OLK-5.10,OLK-6.6,master', description=i18n("要分析的分支列表，逗号分隔")),
    signer_name: Optional[str] = Field(None, description=i18n("提交者姓名")),
    signer_email: Optional[str] = Field(None, description=i18n("提交者邮箱")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    result = run_cvekit('analyze-branches', {
        'cve_id': cve_id,
        'branches': branches,
        'signer_name': signer_name,
        'signer_email': signer_email,
        'gitee_token': gitee_token
    })
    
    if 'error' in result:
        return i18n("分支分析失败: %s") % result['error']
    
    if isinstance(result, dict):
        result = [result]
    
    if not result:
        return i18n("未找到受影响的分支")
    
    table = i18n("| 补丁ID | 目标分支 | 是否受影响 | 适配状态 | 冲突点 | 建议调整文件 |\n")
    table += "|--------|----------|------------|----------|--------|--------------|\n"
    
    for item in result:
        cve_id = item.get(i18n('补丁ID'), '')
        target_branch = item.get(i18n('目标分支'), '')
        is_affected = item.get(i18n('是否受影响'), '')
        adapt_status = item.get(i18n('适配状态'), '')
        conflict_point = item.get(i18n('冲突点'), '')
        suggess_file = item.get(i18n('建议调整文件'), '')
        table += f"| {cve_id} | {target_branch} | {is_affected} | {adapt_status} | {conflict_point} | {suggess_file} |\n"

    res = i18n("分支分析完成，共发现 %d 个受影响的分支:\n\n") % (len(result))
    res += table
    # res += i18n("请确认以上分析结果")
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第五步：
        对于第四步中分析出的受影响分支，分别应用相对应的patch，参数中的patch_path为第四步的冲突点
        若patch应用成功，提交之后，把该分支推送到fork仓，若patch应用失败，尝试解决冲突后，重新执行该步骤
        本地代码位于工作空间里面的仓库名所在的目录
        若没有受影响分支，该步骤可跳过
    """))
def apply_patch(
    cve_id: str = Field(..., description="cve id"),
    branch: Optional[str] = Field(description=i18n("要应用patch的分支名")),
    fork_repo_url: Optional[str] = Field(description=i18n("fork仓库url")),
    patch_path: Optional[str] = Field(description=i18n("patch路径")),
    signer_name: Optional[str] = Field(description=i18n("提交者姓名")),
    signer_email: Optional[str] = Field(None, description=i18n("提交者邮箱")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    result = run_cvekit('apply-patch', {
        'cve_id': cve_id,
        'branch': branch,
        'fork_repo_url': fork_repo_url,
        'patch_path': patch_path,
        'signer_name': signer_name,
        'signer_email': signer_email,
        'gitee_token': gitee_token
    })

    if 'error' in result or 'error' in result.get('status'):
        return i18n("应用patch失败: %s") % (result['error'])
    fix_branch = result.get('fix_branch', '')
    return i18n('patch应用成功, 目标分支: %s, 修复分支: %s, patch: %s') % (branch, fix_branch, patch_path)

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第六步：
        对于第五步中修复成功的分支，提交pr，若用户未提供目标仓库url，则使用默认的目标仓库
        若所有分支均已修复，该步骤可跳过
        参数中的branch是受影响分支名，提交pr的目标分支
    """))
def create_pr(
    cve_id: str = Field(..., description="cve id"),
    branch: Optional[str] = Field(None, description=i18n("受影响分支名，目标分支")),
    fork_repo_url: Optional[str] = Field(None, description=i18n("fork仓库url")),
    repo_url: Optional[str] = Field('https://gitee.com/openeuler/kernel', description=i18n("目标仓库url")),
    signer_name: Optional[str] = Field(None, description=i18n("提交者姓名")),
    signer_email: Optional[str] = Field(None, description=i18n("提交者邮箱")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    result = run_cvekit('create-pr', {
        'cve_id': cve_id,
        'branch': branch,
        'fork_repo_url': fork_repo_url,
        'repo_url': repo_url,
        'gitee_token': gitee_token
    })
    if 'error' in result or 'error' in result.get('status'):
        return i18n("pr提交失败: %s") % (result.get('error'))
    return i18n("pr已提交: %s") % (result.get('pr_html_url'))

if __name__ == "__main__":
    mcp.run()