import subprocess
import json
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from git import Repo, Remote

mcp = FastMCP("管理openEuler社区的issue,repos,pr,以及我的project")

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
        # 执行oegitext命令并解析JSON结果
        result = subprocess.check_output(['oegitext', 'show', 'proj', '-p'], 
                                        text=True, 
                                        stderr=subprocess.STDOUT)
        
        return result
    except subprocess.CalledProcessError as e:
        return e
    except Exception as e:
        return e

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
    repo_type: str = Field(description="仓库属性，有两种：制品仓：src-openeuler，源码仓：openeuler"),
    repo_name: str = Field(description="仓库名。如果未指定，则默认和本地仓库名相同"),
    title: str = Field(description="PR标题"),
    namespace: str = Field(description="Pull Request提交使用的源命名空间(一般是git用户名)。如果未指定，则使用当前本地配置的git用户名"),
    source_branch: str = Field(description="Pull Request提交的源分支。如果未指定，则使用当前分支"),
    base: str = Field(description="Pull Request提交目标分支的名称。如果未指定，则默认为主仓的master分支"),
    body: str = Field(default="", description="PR描述(可选)")
) -> dict:
    """在openEuler社区仓库创建PR，默认源为本地当前仓库的当前分支，目标为主仓的master分支"""
    try:
        head = f"{namespace}:{source_branch}"
        
        # 构建命令
        cmd = [
            'oegitext', 'pull', '-cmd', 'create',
            '-user', repo_type,
            '-repo', repo_name,
            '-title', title,
            '-head', head,
            '-base', base
        ]
        
        if body:
            cmd.extend(['-body', body])
            
        # 执行命令
        result = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {
            "result": result,
            "details": {
                "source_repo": f"{namespace}/{repo_name}",
                "target_repo": f"{repo_type}/{repo_name}",
                "source_branch": source_branch,
                "target_branch": base
            }
        }
    except subprocess.CalledProcessError as e:
        return {"error": e.output}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run()
