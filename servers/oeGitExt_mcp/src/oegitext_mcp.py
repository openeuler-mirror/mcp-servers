import subprocess
import json
import argparse
import logging
from typing import Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from git import Repo, Remote

# 在mcp初始化前添加参数解析
parser = argparse.ArgumentParser()
parser.add_argument('--token', help='oegitext访问Gitee令牌')
args, _ = parser.parse_known_args() 

mcp = FastMCP("管理openEuler社区的issue,repos,pr,以及我的project")

# 初始化oeGitExt，配置gitee私人令牌
def configure_oegitext(token: Optional[str] = None):
    """自动配置oegitext工具"""
    try:
        if token:
            print(f"token: {token}")
            subprocess.run(
                ['oegitext', 'config', '-token', token],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        else:
            print("未检测到token参数，请确保本地已预先配置")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logging.error(f"Token配置失败: {error_msg}")


@mcp.tool()
def get_my_openeuler_issue() -> dict:
    """统计我在openEuler社区所负责的issue"""
    try:
        # 执行oegitext命令并解析JSON结果
        result = subprocess.check_output(['oegitext', 'show', 'issue', '-p'], 
                                        text=True, 
                                        stderr=subprocess.STDOUT)
        
        return result
    except subprocess.CalledProcessError as e:
        return e
    except Exception as e:
        return e

@mcp.tool()
def get_my_openeuler_project() -> dict:
    """查找我在openEuler社区的项目"""
    try:
        # 先配置token
        configure_oegitext(args.token)
        
        # 执行oegitext命令并获取结果
        result = subprocess.check_output(['oegitext', 'show', 'proj', '-p'],
                                        text=True,
                                        stderr=subprocess.STDOUT)
        
        return result
    except subprocess.CalledProcessError as e:
        return {"error": e.output}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def get_my_openeuler_pr(repo_type:str = Field(description="仓库属性，有两种：制品仓：src-openeuler，源码仓：openeuler"), 
                        repo_name:str = Field(description="仓库名")) -> dict:
    """
    查找我在openEuler对应仓库下的pr，如果用户没有指定repo_type，可以执行这个函数两次，都查询一遍
    """
    try:
        # 执行oegitext命令并解析JSON结果
        name = f"{repo_type}/{repo_name}"
        result = subprocess.check_output(['oegitext', 'show', 'pr' , '-name', name, '-p'], 
                                        text=True, 
                                        stderr=subprocess.STDOUT)
        
        return result
    except subprocess.CalledProcessError as e:
        return e
    except Exception as e:
        return e

@mcp.tool()
def create_openeuler_pr(
    target_namespace: str = Field(default=None, description="目标仓库命名空间，有两种：制品仓：src-openeuler，源码仓：openeuler"),
    target_repo_name: str = Field(default=None, description="目标仓库名。如果未指定，则默认和本地仓库名相同"),
    target_branch: str = Field(default=None, description="Pull Request提交目标分支的名称。如果未指定，则默认为主仓的master分支"),
    title: str = Field(description="PR标题"),
    body: str = Field(default="", description="PR描述(可选)"),
    source_namespace: str = Field(default=None, description="Pull Request提交使用的源命名空间(一般是git用户名)。如果未指定，则使用当前本地配置的git用户名"),
    source_repo_name: str = Field(default=None, description="源仓库名。如果未指定，则默认和本地仓库名相同"),
    source_branch: str = Field(default=None, description="Pull Request提交的源分支。如果未指定，则使用当前分支"),
    source_combined: str = Field(default=None, description="源仓库组合格式：namespace/repo_name:branch"),
    target_combined: str = Field(default=None, description="目标仓库组合格式：namespace/repo_name:branch")
) -> dict:
    """在openEuler社区仓库创建PR，默认源为本地当前仓库的当前分支，目标为主仓的master分支"""
    try:
        # 解析组合格式参数
        if source_combined and isinstance(source_combined, str):
            source_parts = source_combined.split('/')
            if len(source_parts) == 2:
                source_namespace = source_parts[0]
                repo_branch = source_parts[1].split(':')
                if len(repo_branch) == 2:
                    source_repo_name = repo_branch[0]
                    source_branch = repo_branch[1]
        
        if target_combined and isinstance(target_combined, str):
            target_parts = target_combined.split('/')
            if len(target_parts) == 2:
                target_namespace = target_parts[0]
                repo_branch = target_parts[1].split(':')
                if len(repo_branch) == 2:
                    target_repo_name = repo_branch[0]
                    target_branch = repo_branch[1]
        
        # 设置默认值
        try:
            if not source_namespace or not source_repo_name or not source_branch:
                git_namespace, git_repo_name, git_branch = get_git_repo_info()
                if not source_namespace:
                    source_namespace = git_namespace
                if not source_repo_name:
                    source_repo_name = git_repo_name
                if not source_branch:
                    source_branch = git_branch
        except Exception as e:
            return {"error": str(e)}
            
        if not target_namespace:
            target_namespace = "openeuler"
        if not target_repo_name:
            target_repo_name = source_repo_name
        if not target_branch:
            target_branch = "master"
            
        head = f"{source_namespace}/{source_repo_name}:{source_branch}"
        
        # 构建命令
        cmd = [
            'oegitext', 'pull', '-cmd', 'create',
            '-user', target_namespace,
            '-repo', target_repo_name,
            '-title', title,
            '-head', head,
            '-base', target_branch
        ]
        
        if body:
            cmd.extend(['-body', body])
            
        # 执行命令
        result = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {
            "result": result,
            "details": {
                "source_repo": f"{source_namespace}/{target_repo_name}",
                "target_repo": f"{target_namespace}/{target_repo_name}",
                "source_branch": source_branch,
                "target_branch": target_branch
            }
        }
    except subprocess.CalledProcessError as e:
        return {"error": e.output}
    except Exception as e:
        return {"error": str(e)}

def get_git_repo_info():
    try:
        namespace = subprocess.check_output(['git', 'config', 'user.name'], text=True).strip()
        repo_name = Repo('.').remotes[0].url.split('/')[-1].replace('.git', '')
        branch = Repo('.').active_branch.name
        return namespace, repo_name, branch
    except Exception as e:
        raise Exception(f"获取本地git仓库信息失败: {str(e)}")

if __name__ == "__main__":
    # 配置oegitext的token，用于访问Gitee
    configure_oegitext(args.token)
    
    # Initialize and run the server
    mcp.run()
