#!/usr/bin/env python3
import os
import subprocess
from mcp.server.fastmcp import FastMCP, Context

PASS_CMD = "/usr/bin/pass"
mcp = FastMCP("密码管理器")

@mcp.tool()
def list_passwords(ctx: Context) -> dict:
    """列出所有密码条目"""
    passwords = []
    pass_dir = os.path.expanduser("~/.password-store")
    for root, _, files in os.walk(pass_dir):
        for f in files:
            if f.endswith(".gpg"):
                rel_path = os.path.relpath(root, pass_dir)
                if rel_path == ".":
                    passwords.append(f[:-4])
                else:
                    passwords.append(f"{rel_path}/{f[:-4]}")
    return {"passwords": passwords}

@mcp.tool()
def get_password(ctx: Context, name: str) -> dict:
    """获取指定密码
    
    Args:
        name: 密码名称
    """
    try:
        result = subprocess.run(
            [PASS_CMD, "show", name],
            capture_output=True,
            text=True,
            check=True,
            timeout=25
        )
        return {"password": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "code": e.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Password command timed out", "code": 408}

@mcp.tool()
def store_password(ctx: Context, name: str, value: str) -> dict:
    """存储新密码
    
    Args:
        name: 密码名称
        value: 密码值
    """
    try:
        # First insert command
        subprocess.run(
            [PASS_CMD, "insert", "-m", name],
            input=value,
            text=True,
            check=True,
            timeout=25
        )
        return {"status": "success"}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "code": e.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Password command timed out", "code": 408}

if __name__ == '__main__':
    mcp.run()