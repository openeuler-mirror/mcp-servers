#!/usr/bin/env python3
import subprocess
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("软件包管理")

@mcp.tool()
def query_packages(ctx: Context, package_name: str = "") -> str:
    """查询软件包信息
    
    Args:
        package_name: 要查询的软件包名(可选)
    """
    try:
        if package_name:
            cmd = ["dnf", "search", package_name]
        else:
            cmd = ["dnf", "list", "--installed"]
            
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"查询失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def install_package(ctx: Context, package_name: str) -> str:
    """安装软件包
    
    Args:
        package_name: 要安装的软件包名
    """
    try:
        result = subprocess.run(
            ["sudo", "dnf", "install", "-y", package_name],
            check=True,
            capture_output=True,
            text=True
        )
        return f"安装成功: {result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"安装失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def remove_package(ctx: Context, package_name: str) -> str:
    """卸载软件包
    
    Args:
        package_name: 要卸载的软件包名
    """
    try:
        result = subprocess.run(
            ["sudo", "dnf", "remove", "-y", package_name],
            check=True,
            capture_output=True,
            text=True
        )
        return f"卸载成功: {result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"卸载失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

if __name__ == "__main__":
    mcp.run()