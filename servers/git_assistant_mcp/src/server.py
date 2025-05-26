from pydantic import Field
from typing import Optional, List
from mcp.server.fastmcp import FastMCP
from git import Repo, InvalidGitRepositoryError, GitCommandError
import os

mcp = FastMCP("git_assistant_mcp")

@mcp.tool()
def git_clone(
    repo_url: str = Field(description="Git仓库URL"),
    local_path: str = Field(default=".", description="本地存放路径"),
    branch: Optional[str] = Field(default=None, description="指定分支")
) -> str:
    """克隆Git仓库到本地"""
    try:
        if branch:
            Repo.clone_from(repo_url, local_path, branch=branch)
        else:
            Repo.clone_from(repo_url, local_path)
        return f"成功克隆仓库到: {local_path}"
    except GitCommandError as e:
        return f"克隆失败: {str(e)}"

@mcp.tool()
def git_init(
    repo_path: str = Field(description="仓库路径")
) -> str:
    """初始化Git仓库"""
    try:
        repo = Repo.init(path=repo_path, mkdir=True)
        return f"已初始化Git仓库: {repo.git_dir}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def git_status(
    repo_path: str = Field(default=".", description="仓库路径")
) -> str:
    """查看Git仓库状态"""
    try:
        repo = Repo(repo_path)
        return repo.git.status()
    except InvalidGitRepositoryError:
        return "错误: 路径不是Git仓库"

@mcp.tool()
def git_commit(
    repo_path: str = Field(default=".", description="仓库路径"),
    message: str = Field(description="提交信息"),
    files: Optional[List[str]] = Field(default=None, description="指定文件列表")
) -> str:
    """提交更改"""
    try:
        repo = Repo(repo_path)
        if files:
            repo.index.add(files)
        else:
            repo.git.add('-A')
        repo.index.commit(message)
        return "提交成功"
    except Exception as e:
        return f"提交失败: {str(e)}"

@mcp.tool()
def git_push(
    repo_path: str = Field(default=".", description="仓库路径"),
    remote: str = Field(default="origin", description="远程名称"),
    branch: str = Field(default=None, description="分支名称")
) -> str:
    """推送更改到远程仓库"""
    try:
        repo = Repo(repo_path)
        if not branch:
            branch = repo.active_branch.name
        repo.git.push(remote, branch)
        return f"成功推送到 {remote}/{branch}"
    except Exception as e:
        return f"推送失败: {str(e)}"

@mcp.tool()
def create_branch(
    branch_name: str = Field(description="新分支名称"),
    repo_path: str = Field(default=".", description="仓库路径")
) -> str:
    """创建新分支"""
    try:
        repo = Repo(repo_path)
        repo.git.checkout('-b', branch_name)
        return f"已创建并切换到新分支: {branch_name}"
    except Exception as e:
        return f"创建分支出错: {str(e)}"

if __name__ == "__main__":
    mcp.run()