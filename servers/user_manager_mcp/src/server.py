#!/usr/bin/env python3
import subprocess
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("用户管理")

@mcp.tool()
def add_user(ctx: Context, username: str, password: str = "") -> str:
    """添加用户
    
    Args:
        username: 用户名
        password: 密码(可选)
    """
    try:
        cmd = ["sudo", "useradd", username]
        if password:
            cmd.extend(["-p", password])
            
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        return f"用户 {username} 添加成功"
    except subprocess.CalledProcessError as e:
        return f"添加用户失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool() 
def delete_user(ctx: Context, username: str) -> str:
    """删除用户
    
    Args:
        username: 要删除的用户名
    """
    try:
        result = subprocess.run(
            ["sudo", "userdel", "-r", username],
            check=True,
            capture_output=True,
            text=True
        )
        return f"用户 {username} 删除成功"
    except subprocess.CalledProcessError as e:
        return f"删除用户失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

@mcp.tool()
def modify_user(ctx: Context, username: str, new_name: str = None, password: str = None) -> str:
    """修改用户信息
    
    Args:
        username: 原用户名
        new_name: 新用户名(可选)
        password: 新密码(可选)
    """
    try:
        if new_name:
            subprocess.run(
                ["sudo", "usermod", "-l", new_name, username],
                check=True,
                capture_output=True,
                text=True
            )
            username = new_name
            
        if password:
            subprocess.run(
                ["sudo", "passwd", username],
                input=f"{password}\n{password}",
                text=True,
                check=True
            )
            
        return f"用户 {username} 修改成功"
    except subprocess.CalledProcessError as e:
        return f"修改用户失败: {e.stderr}"
    except Exception as e:
        return f"发生错误: {str(e)}"

if __name__ == "__main__":
    mcp.run()