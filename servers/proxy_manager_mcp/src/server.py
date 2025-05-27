#!/usr/bin/env python3
import os
import subprocess
from typing import Dict, Any
from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("proxy_manager_mcp")

SQUID_CONF = "/etc/squid/squid.conf"

def _reload_squid():
    """重新加载squid配置"""
    subprocess.run(["systemctl", "reload", "squid"], check=True)

@mcp.tool()
def set_proxy(
    config: str = Field(..., description="Squid代理配置内容")
) -> Dict[str, Any]:
    """设置代理配置"""
    try:
        with open(SQUID_CONF, "w") as f:
            f.write(config)
        _reload_squid()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()    
def get_proxy_status() -> Dict[str, Any]:
    """获取代理状态"""
    try:
        result = subprocess.run(
            ["systemctl", "status", "squid"],
            capture_output=True,
            text=True
        )
        return {
            "status": result.stdout,
            "active": "active (running)" in result.stdout
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def restart_proxy() -> Dict[str, Any]:
    """重启代理服务"""
    try:
        _reload_squid()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def list_proxy_settings() -> Dict[str, Any]:
    """列出当前代理设置"""
    try:
        with open(SQUID_CONF, "r") as f:
            return {"config": f.read()}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    mcp.run()