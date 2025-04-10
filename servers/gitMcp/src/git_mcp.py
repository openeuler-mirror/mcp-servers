from pydantic import Field
from typing import Optional, List
from mcp.server.fastmcp import FastMCP
from git import Repo, InvalidGitRepositoryError, GitCommandError
import os
import inquirer

mcp = FastMCP("gitMcp")

@mcp.tool()
def add_commit_and_push(
    commit_message: str = Field(default="auto commit", description="提交信息（默认为'auto commit by git_mcp'）"),
    user_name: Optional[str] = Field(default=None, description="提交时使用的Git用户名。如果未指定，则从当前本地的Git配置中获取"),
    user_email: Optional[str] = Field(default=None, description="提交时使用的Git用户邮箱信息。如果未指定，则从当前本地的Git配置中获取"),
    repo_path: str = Field(default=None, description="仓库路径"),
    files: Optional[List[str]] = Field(default=None, description="要添加的文件列表。如果未指定，则添加所有修改")
) -> str:
    """添加本地修改（可选择文件），提交并推送到远程仓库。如果没有文件需要提交，则直接推送"""
    try:
        if not os.path.exists(repo_path):
            return f"错误: 路径 '{repo_path}' 不存在"
        
        repo = Repo(repo_path)

        # 尝试读取现有配置
        try:
            with repo.config_reader() as config:
                current_name = config.get_value("user", "name", None)
                current_email = config.get_value("user", "email", None)
        except Exception as e:
            if "No section" in str(e):
                return "错误: 本地Git用户信息未配置，请提供user_name和user_email参数"
            current_name = None
            current_email = None

        # 验证用户信息配置
        if not (user_name or current_name):
            return "错误: 本地未配置Git用户名(user.name)且未提供user_name参数"
        if not (user_email or current_email):
            return "错误: 本地未配置Git邮箱(user.email)且未提供user_email参数"

        # 设置用户信息（如果提供了新参数）
        if user_name or user_email:
            with repo.config_writer() as config:
                if user_name:
                    config.set_value("user", "name", user_name)
                if user_email:
                    config.set_value("user", "email", user_email)

        # 检查是否有变更
        changed_files = repo.git.status('--porcelain').splitlines()
        if not changed_files:
            print("没有文件需要提交，直接推送")
        else:
            # 添加文件
            if files:
                repo.index.add(files)
                staged_files = files
            else:
                repo.git.add('-A')
                staged_files = repo.git.diff('--cached', '--name-only').splitlines()

            print("成功添加以下文件:\n" + "\n".join(staged_files))

            # 提交修改
            repo.git.commit('-m', commit_message)
            print(f"提交成功，commit信息为: {commit_message}")

        # 推送修改（自动处理上游分支）
        try:
            repo.git.push()
        except GitCommandError as push_error:
            if 'has no upstream branch' in push_error.stderr:
                repo.git.push('--set-upstream', 'origin', repo.active_branch.name)
            else:
                raise

        return "成功: 操作已完成"
    except InvalidGitRepositoryError:
        return f"错误: 路径 '{repo_path}' 不是有效的Git仓库"
    except GitCommandError as e:
        return f"Git操作失败: {e.stderr.strip()}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def git_status(repo_path: str = Field(default=None, description="仓库路径")) -> str:
    """查看Git仓库状态"""
    try:
        repo = Repo(repo_path)
        return repo.git.status()
    except InvalidGitRepositoryError:
        return "错误：路径不是Git仓库"

@mcp.tool()
def git_diff_unstaged(repo_path: str = Field(description="仓库路径")) -> str:
    """查看未暂存的变更"""
    try:
        repo = Repo(repo_path)
        return repo.git.diff()
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def git_diff_staged(repo_path: str = Field(description="仓库路径")) -> str:
    """查看已暂存的变更"""
    try:
        repo = Repo(repo_path)
        return repo.git.diff("--cached")
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def git_diff(
    repo_path: str = Field(description="仓库路径"),
    target: str = Field(description="对比目标分支或提交")
) -> str:
    """对比分支或提交"""
    try:
        repo = Repo(repo_path)
        return repo.git.diff(target)
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def git_reset(repo_path: str = Field(description="仓库路径")) -> str:
    """重置暂存区"""
    try:
        repo = Repo(repo_path)
        repo.index.reset()
        return "暂存区已重置"
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def git_show(
    repo_path: str = Field(description="仓库路径"),
    revision: str = Field(description="提交hash或分支名称")
) -> str:
    """查看提交详情"""
    try:
        repo = Repo(repo_path)
        commit = repo.commit(revision)
        output = [
            f"Commit: {commit.hexsha}\n"
            f"Author: {commit.author}\n"
            f"Date: {commit.authored_datetime}\n"
            f"Message: {commit.message}\n"
        ]
        if commit.parents:
            parent = commit.parents[0]
            diff = parent.diff(commit, create_patch=True)
        else:
            diff = commit.diff(git.NULL_TREE, create_patch=True)
        for d in diff:
            output.append(f"\n--- {d.a_path}\n+++ {d.b_path}\n")
            output.append(d.diff.decode('utf-8'))
        return "".join(output)
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def create_branch(
    branch_name: str = Field(description="新分支名称"),
    repo_path: str = Field(default=None, description="仓库路径")
) -> str:
    """创建一个新的git分支"""
    try:
        repo = Repo(repo_path)
        repo.git.checkout('-b', branch_name)
        return f"已创建并切换到新分支: {branch_name}"
    except Exception as e:
        return f"创建分支出错: {str(e)}"

@mcp.tool()
def list_branches(repo_path: str = Field(default=None, description="仓库路径")) -> str:
    """列出所有本地和远程分支"""
    try:
        repo = Repo(repo_path)
        current = repo.active_branch.name
        output = [f"* {current} (当前分支)"]
        
        # 处理本地分支
        for branch in repo.branches:
            if branch.name != current:
                output.append(f"  {branch.name}")
                
        # 处理远程分支
        output.append("\n远程分支:")
        for ref in repo.remote().refs:
            if ref.name.split('/')[-1] != 'HEAD':
                output.append(f"  {ref.name}")
                
        return '\n'.join(output)
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def get_git_config(repo_path: str = Field(default=None, description="仓库路径")) -> str:
    """获取当前配置的git用户信息"""
    try:
        repo = Repo(repo_path)
        try:
            with repo.config_reader() as config:
                name = config.get_value('user', 'name', None)
                email = config.get_value('user', 'email', None)
        except Exception:
            return {"status": "not_configured", "message": "Git用户信息未配置"}
            
        if not name and not email:
            return {"status": "not_configured", "message": "Git用户信息未配置"}
            
        return {
            "status": "ok",
            "user.name": name,
            "user.email": email
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def git_init(repo_path: str = Field(description="仓库路径")) -> str:
    """初始化Git仓库"""
    try:
        repo = Repo.init(path=repo_path, mkdir=True)
        return f"已初始化Git仓库: {repo.git_dir}"
    except Exception as e:
        return f"错误：{str(e)}"

@mcp.tool()
def add_remote(
    remote_name: str = Field(description="远程仓库名称"),
    remote_url: str = Field(description="远程仓库URL"),
    repo_path: str = Field(default=None, description="仓库路径")
) -> str:
    """添加远程Git仓库"""
    try:
        if not remote_name or not remote_url:
            return "错误: 必须提供远程仓库名称和URL"
            
        repo = Repo(repo_path)
        remote = repo.create_remote(remote_name, remote_url)
        return f"成功添加远程仓库: {remote_name} -> {remote_url}"
    except InvalidGitRepositoryError:
        return f"错误: 路径 '{repo_path}' 不是有效的Git仓库"
    except GitCommandError as e:
        if 'remote .* already exists' in str(e):
            return f"错误: 远程仓库 '{remote_name}' 已存在"
        return f"Git操作失败: {str(e)}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def git_pull(
    repo_path: str = Field(default=None, description="仓库路径"),
    remote_name: str = Field(default="origin", description="远程名称"),
    branch_name: str = Field(default=None, description="分支名称")
) -> str:
    """从远程仓库拉取代码"""
    try:
        repo = Repo(repo_path)
        current_branch = repo.active_branch.name
        pull_branch = branch_name if branch_name else current_branch
        
        try:
            repo.git.pull(remote_name, pull_branch)
            return f"成功从 {remote_name}/{pull_branch} 拉取代码"
        except GitCommandError as e:
            if 'no tracking information' in str(e):
                return f"错误: 分支 {pull_branch} 没有设置上游跟踪分支"
            elif 'conflict' in str(e):
                return "错误: 拉取时发生合并冲突，请先解决冲突"
            elif 'Could not resolve host' in str(e):
                return "错误: 无法连接到远程仓库，请检查网络连接"
            raise
            
    except InvalidGitRepositoryError:
        return f"错误: 路径 '{repo_path}' 不是有效的Git仓库"
    except Exception as e:
        return f"错误: {str(e)}"

if __name__ == "__main__":
    mcp.run()