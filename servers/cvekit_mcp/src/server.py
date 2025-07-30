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
    branches: Optional[str] = Field(None, description="要分析的分支列表，逗号分隔"),
    signer_name: Optional[str] = Field(None, description="提交者姓名"),
    signer_email: Optional[str] = Field(None, description="提交者邮箱"),
    gitee_token: Optional[str] = Field(None, description="Gitee访问令牌(可选)")
) -> str:
    """
    该函数是CVE修复流程的第四步：
        分析introduced_commit在本地仓库的哪些分支被引入，如果引入的话，是否被fixed了，以此来分析哪些分支需要应用补丁
        并检查从上游获取的补丁直接应用，是否存在冲突
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

if __name__ == "__main__":
    mcp.run()