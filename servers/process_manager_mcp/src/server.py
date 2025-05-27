import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("进程管理工具")

def run_command(cmd, args=None):
    """执行系统命令并返回结果"""
    try:
        command = [cmd] + (args or [])
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "output": e.stderr}

@mcp.tool()
def list_processes() -> dict:
    """获取系统进程列表"""
    return run_command("ps", ["-aux"])

@mcp.tool()
def monitor_processes() -> dict:
    """监控系统进程状态"""
    return run_command("top", ["-b", "-n", "1"])

@mcp.tool()
def kill_process(pid: int) -> dict:
    """
    终止指定进程
    :param pid: 进程ID
    """
    return run_command("kill", ["-9", str(pid)])

if __name__ == "__main__":
    mcp.run()