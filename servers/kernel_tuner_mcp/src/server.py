from pydantic import Field
from typing import Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import re

mcp = FastMCP("kernelTuner")

PARAM_PATTERN = r'^[a-zA-Z0-9_.-]+$'

def _run_sysctl_command(cmd: list) -> dict:
    """执行sysctl命令的公共函数"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {"result": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unknown error: {str(e)}"}

@mcp.tool()
def get_param(
    param: str = Field(..., description="要获取的内核参数名")
) -> dict:
    """获取内核参数值
    
    示例用法:
    1. 获取vm.swappiness参数的值
    """
    if not re.match(PARAM_PATTERN, param):
        return {"error": "Invalid parameter name"}
    
    return _run_sysctl_command(['sysctl', '-n', param])

@mcp.tool()
def set_param(
    param: str = Field(..., description="要设置的内核参数名"),
    value: str = Field(..., description="要设置的值")
) -> dict:
    """设置内核参数值
    
    示例用法:
    1. 设置vm.swappiness为60
    """
    if not re.match(PARAM_PATTERN, param):
        return {"error": "Invalid parameter name"}
    if not value:
        return {"error": "Value is required"}
    
    return _run_sysctl_command(['sysctl', '-w', f'{param}={value}'])

@mcp.tool()
def list_params() -> dict:
    """列出所有可用的内核参数
    
    示例用法:
    1. 列出系统支持的所有内核参数
    """
    result = _run_sysctl_command(['sysctl', '-a'])
    if "error" in result:
        return result
    
    params = [line.split('=')[0].strip() 
             for line in result["result"].split('\n') if '=' in line]
    return {"params": params}

if __name__ == "__main__":
    mcp.run()