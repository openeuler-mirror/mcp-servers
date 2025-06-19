#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, List
from mcp.server.fastmcp import FastMCP
import subprocess
from pathlib import Path
import json

mcp = FastMCP("system_language_mcp")

@mcp.tool()
def get_current_locale() -> Dict[str, str]:
    """获取当前系统locale设置
    
    示例用法:
    1. 获取当前系统locale配置
    """
    try:
        result = subprocess.run(["locale"], 
                              capture_output=True, text=True)
        return {"status": "success", "locale": result.stdout}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def set_locale(
    locale: str = Field(..., description="要设置的locale名称，如zh_CN.UTF-8")
) -> Dict[str, str]:
    """设置系统locale
    
    示例用法:
    1. 设置locale为zh_CN.UTF-8
    2. 设置locale为en_US.UTF-8
    """
    try:
        subprocess.run(["localectl", "set-locale", f"LANG={locale}"], 
                      check=True)
        return {"status": "success", "message": f"Locale set to {locale}"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def list_available_locales() -> Dict[str, List[str]]:
    """列出系统可用的locale
    
    示例用法:
    1. 列出所有可用locale
    2. 过滤中文locale: list_available_locales | grep zh
    """
    try:
        result = subprocess.run(["localectl", "list-locales"], 
                              capture_output=True, text=True)
        return {"status": "success", "locales": result.stdout.splitlines()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()
