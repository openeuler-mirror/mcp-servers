#!/usr/bin/env python3
import subprocess
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("rpm-ostree管理工具")

@mcp.tool()
def get_status(ctx: Context) -> str:
    """获取当前rpm-ostree状态"""
    try:
        result = subprocess.run(
            ["rpm-ostree", "status"],
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"获取状态失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def deploy(ctx: Context, ref: str) -> str:
    """部署新的ostree提交
    
    Args:
        ref: 要部署的引用(如:stable或特定提交ID)
    """
    try:
        result = subprocess.run(
            ["sudo", "rpm-ostree", "deploy", ref],
            check=True,
            capture_output=True,
            text=True
        )
        return f"部署成功，需要重启生效:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"部署失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def rollback(ctx: Context) -> str:
    """回滚到之前的部署"""
    try:
        result = subprocess.run(
            ["sudo", "rpm-ostree", "rollback"],
            check=True,
            capture_output=True,
            text=True
        )
        return f"回滚成功，需要重启生效:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"回滚失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def upgrade(ctx: Context) -> str:
    """升级系统到最新版本"""
    try:
        result = subprocess.run(
            ["sudo", "rpm-ostree", "upgrade"],
            check=True,
            capture_output=True,
            text=True
        )
        return f"升级成功，需要重启生效:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"升级失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def rebase(ctx: Context, remote: str, branch: str) -> str:
    """重新基于指定的远程分支
    
    Args:
        remote: 远程名称(如:upstream)
        branch: 分支名称(如:stable)
    """
    try:
        result = subprocess.run(
            ["sudo", "rpm-ostree", "rebase", f"{remote}:{branch}"],
            check=True,
            capture_output=True,
            text=True
        )
        return f"重新基于成功，需要重启生效:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"重新基于失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

if __name__ == "__main__":
    mcp.run()