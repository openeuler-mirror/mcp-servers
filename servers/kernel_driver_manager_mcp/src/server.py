import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("内核驱动管理工具")

def run_command(cmd, args=None):
    """执行系统命令并返回结构化结果"""
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
def list_modules() -> dict:
    """列出已加载的内核模块"""
    return run_command("lsmod")

@mcp.tool()
def module_info(module: str) -> dict:
    """查看内核模块详细信息"""
    return run_command("modinfo", [module])

@mcp.tool()
def load_module(module: str) -> dict:
    """加载内核模块"""
    return run_command("modprobe", [module])

@mcp.tool()
def unload_module(module: str) -> dict:
    """卸载内核模块"""
    return run_command("rmmod", [module])

if __name__ == "__main__":
    mcp.run()