import subprocess
import shlex
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("缓存管理工具")

def execute_redis_command(command):
    """执行Redis命令"""
    try:
        cmd = f"redis-cli {command}"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "status": "success",
            "output": result.stdout.strip()
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": str(e),
            "output": e.stderr.strip()
        }

def execute_memcached_command(command):
    """执行Memcached命令"""
    try:
        cmd = f"memcached-tool localhost:11211 {command}"
        result = subprocess.run(
            shlex.split(cmd),
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "status": "success", 
            "output": result.stdout.strip()
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": str(e),
            "output": e.stderr.strip()
        }

@mcp.tool()
def redis(command: str) -> dict:
    """
    执行Redis命令
    :param command: Redis命令字符串
    :return: 执行结果
    """
    return execute_redis_command(command)

@mcp.tool()
def memcached(command: str) -> dict:
    """
    执行Memcached命令
    :param command: Memcached命令字符串
    :return: 执行结果
    """
    return execute_memcached_command(command)

if __name__ == "__main__":
    mcp.run()