import subprocess
import json
import argparse
import logging
from typing import Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("CVE修复流程自动化工具，提供CVE分析、补丁适配等功能")

# 配置参数解析
parser = argparse.ArgumentParser()
parser.add_argument('--gitee-token', help='Gitee访问令牌')
args, _ = parser.parse_known_args()

def run_cvekit(action: str, params: dict) -> dict:
    """执行cvekit命令并返回结果"""
    try:
        # 构建基础命令
        cmd = ['cvekit', f'--action={action}']
        if action != 'setup-env':
            cmd.append('--json')
        
        # 添加公共参数
        if 'issue_url' in params:
            cmd.append(f'--issue-url={params["issue_url"]}')
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        return json.loads(result.stdout)
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logging.error(f"cvekit执行失败: {error_msg}")
        return {"error": error_msg, "command": " ".join(cmd)}
    except json.JSONDecodeError:
        logging.error("cvekit输出非JSON格式")
        return {"error": "Invalid JSON output", "output": result.stdout}

@mcp.tool()
def parse_issue(
    issue_url: str = Field(..., description="Gitee Issue URL"),
    gitee_token: Optional[str] = Field(None, description="Gitee访问令牌(可选)")
) -> str:
    """
    该函数是CVE修复流程的第一步：
        通过调用gitee的api，解析gitee issue URL并获取基本信息
        在这里将通过issue_url解析得到的issue_info以json格式反馈给用户
        主要告知用户我们获取的issue_id, cve_id, org_name, repo_name, affected_versions这些是否正确，需要用户确认
    """
    result = run_cvekit('parse-issue', {
        'issue_url': issue_url,
        'gitee_token': gitee_token
    })
    
    if 'error' in result:
        return f"解析Issue失败: {result['error']}"
    
    data = result.get('data', {})
    return (
        f"已解析Issue {data.get('issue_id', '')}:\n"
        f"- CVE ID: {data.get('cve_id', '')}\n"
        f"- 组织: {data.get('org_name', '')}\n"
        f"- 仓库: {data.get('repo_name', '')}\n"
        f"- 受影响版本: {data.get('affected_versions', '')}\n"
        "请确认以上信息是否正确"
    )

@mcp.tool()
def setup_env(
    fork_repo_url: str = Field(..., description="Fork仓库URL"),
    clone_dir: str = Field(..., description="本地仓库克隆目录"),
    gitee_token: Optional[str] = Field(None, description="Gitee访问令牌(可选)")
) -> dict:
    """
    该函数是CVE修复流程的第二步：
        设置仓库环境，克隆官方仓库，添加fork远程
    """

    run_cvekit('setup-env', {
        'fork_repo_url': fork_repo_url,
        'clone_dir': clone_dir,
        'gitee_token': gitee_token
    })

    return f"仓库已经下载到{clone_dir}路径下"

@mcp.tool()
def get_commits(
    issue_url: str = Field(..., description="Gitee Issue URL"),
    gitee_token: Optional[str] = Field(None, description="Gitee访问令牌(可选)")
) -> str:
    """
    该函数是CVE修复流程的第三步：
        获取漏洞相关的真实上游提交信息，并将获取到的commit告知给用户
    """
    result = run_cvekit('get-commits', {
        'issue_url': issue_url,
        'gitee_token': gitee_token
    })
    
    # Check for errors first
    if 'error' in result:
        return f"获取提交信息失败: {result['error']}"
    
    return (
        f"已获取CVE {result.get('cve_id', '')}的提交信息:\n"
        f"- 引入漏洞的提交: {result.get('introduced', '')}\n"
        f"- 修复漏洞的提交: {result.get('fixed', '')}\n"
        "请确认以上提交信息是否正确"
    )

@mcp.tool()
def analyze_branches(
    issue_url: str = Field(..., description="Gitee Issue URL"),
    branches: Optional[str] = Field('OLK-5.10,OLK-6.6,master', description="要分析的分支列表，逗号分隔"),
    signer_name: Optional[str] = Field(None, description="提交者姓名"),
    signer_email: Optional[str] = Field(None, description="提交者邮箱"),
    gitee_token: Optional[str] = Field(None, description="Gitee访问令牌(可选)")
) -> str:
    """
    该函数是CVE修复流程的第四步：
        分析introduced_commit在本地仓库的哪些分支被引入，如果引入的话，是否被fixed了，以此来分析哪些分支需要应用补丁
        并检查从上游获取的补丁直接应用，是否存在冲突
        该步骤中的参数branches为kernel的分支名，和issue分析中的受影响版本并不完全一致，若用户未指定要分析的分支名，采
        用默认值即可
    """
    result = run_cvekit('analyze-branches', {
        'issue_url': issue_url,
        'branches': branches,
        'signer_name': signer_name,
        'signer_email': signer_email,
        'gitee_token': gitee_token
    })
    
    if 'error' in result:
        return f"分支分析失败: {result['error']}"
    
    if isinstance(result, dict):
        result = [result]
    
    if not result:
        return "未找到受影响的分支"
    
    table = "| 补丁ID | 目标分支 | 是否受影响 | 适配状态 | 冲突点 | 建议调整文件 |\n"
    table += "|--------|----------|------------|----------|--------|--------------|\n"
    
    for item in result:
        table += (
            f"| {item.get('补丁ID', '')} | {item.get('目标分支', '')} | "
            f"{item.get('是否受影响', '')} | {item.get('适配状态', '')} | "
            f"{item.get('冲突点', '')} | {item.get('建议调整文件', '')} |\n"
        )
    
    return (
        f"分支分析完成，共发现 {len(result)} 个受影响的分支:\n\n"
        f"{table}\n"
        "请确认以上分析结果"
    )

@mcp.tool()
def apply_patch(
    issue_url: str = Field(..., description="Gitee Issue URL"),
    branch: Optional[str] = Field(description="要应用patch的分支名"),
    fork_repo_url: Optional[str] = Field(description="fork仓库url"),
    patch_path: Optional[str] = Field(description="patch路径"),
    signer_name: Optional[str] = Field(description="提交者姓名"),
    signer_email: Optional[str] = Field(None, description="提交者邮箱"),
    gitee_token: Optional[str] = Field(None, description="Gitee访问令牌(可选)")
) -> str:
    """
    该函数是CVE修复流程的第五步：
        对于第四步中分析出的受影响分支，分别应用相对应的patch，参数中的patch_path为第四步的冲突点，
        若patch应用成功，提交之后，把该分支推送到fork仓，若patch应用失败，尝试解决冲突后，重新执行该步骤
    """
    result = run_cvekit('apply-patch', {
        'issue_url': issue_url,
        'branch': branch,
        'fork_repo_url': fork_repo_url,
        'patch_path': patch_path,
        'signer_name': signer_name,
        'signer_email': signer_email,
        'gitee_token': gitee_token
    })

    if 'error' in result or 'error' in result.get('status'):
        return f"应用patch失败: {result['error']}"
    return 'patch应用成功'

@mcp.tool()
def create_pr(
    issue_url: str = Field(..., description="Gitee Issue URL"),
    branch: Optional[str] = Field(None, description="提交pr源分支名和目标分支名"),
    fork_repo_url: Optional[str] = Field(None, description="fork仓库url"),
    repo_url: Optional[str] = Field('https://gitee.com/openeuler/kernel', description="目标仓库url"),
    signer_name: Optional[str] = Field(None, description="提交者姓名"),
    signer_email: Optional[str] = Field(None, description="提交者邮箱"),
    gitee_token: Optional[str] = Field(description="Gitee访问令牌")
) -> str:
    """
    该函数是CVE修复流程的第六步：
        对于第五步中推送成功的分支，提交pr，若用户未提供目标仓库url，则使用默认的目标仓库
    """
    result = run_cvekit('create-pr', {
        'issue_url': issue_url,
        'branch': branch,
        'fork_repo_url': fork_repo_url,
        'repo_url': repo_url,
        'gitee_token': gitee_token
    })
    if 'error' in result or 'error' in result.get('status'):
        return f"pr提交失败: {result.get('error')}"
    return f"pr已提交: {result.get('pr_html_url')}"

if __name__ == "__main__":
    mcp.run()