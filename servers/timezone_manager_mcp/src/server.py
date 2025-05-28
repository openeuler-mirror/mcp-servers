from pydantic import Field
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import argparse

mcp = FastMCP("timezoneManagerMcp")

@mcp.tool()
def get_timezone() -> Dict[str, str]:
    """获取当前系统时区
    
    返回:
    {
        "timezone": str  # 当前系统时区
    }
    """
    try:
        result = subprocess.run(["timedatectl", "show", "--property=Timezone", "--value"], 
                              capture_output=True, text=True, check=True)
        return {"timezone": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"error": f"Failed to get timezone: {e.stderr}"}

@mcp.tool()
def set_timezone(
    timezone: str = Field(..., description="要设置的时区名称，如'Asia/Shanghai'")
) -> Dict[str, str]:
    """设置系统时区
    
    示例用法:
    1. 设置时区为Asia/Shanghai
    
    返回:
    {
        "status": str,  # 操作状态
        "message": str  # 详细信息
    }
    """
    try:
        subprocess.run(["timedatectl", "set-timezone", timezone], check=True)
        return {"status": "success", "message": f"Timezone set to {timezone}"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Failed to set timezone: {e.stderr}"}

@mcp.tool()
def list_timezones(
    filter: Optional[str] = Field(default=None, description="时区名称过滤")
) -> Dict[str, List[str]]:
    """列出所有可用时区
    
    示例用法:
    1. 列出所有包含'Asia'的时区
    
    返回:
    {
        "timezones": List[str]  # 时区列表
    }
    """
    try:
        result = subprocess.run(["timedatectl", "list-timezones"], 
                              capture_output=True, text=True, check=True)
        timezones = result.stdout.splitlines()
        if filter:
            timezones = [tz for tz in timezones if filter.lower() in tz.lower()]
        return {"timezones": timezones}
    except subprocess.CalledProcessError as e:
        return {"error": f"Failed to list timezones: {e.stderr}"}

if __name__ == "__main__":
    mcp.run()