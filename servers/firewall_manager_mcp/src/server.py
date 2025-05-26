#!/usr/bin/env python3
import subprocess
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("Firewall Manager")

def run_firewall_cmd(args: List[str]) -> str:
    """执行firewall-cmd命令并返回结果"""
    try:
        result = subprocess.run(
            ["firewall-cmd"] + args,
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

@mcp.tool()
def get_status(ctx: Context) -> Dict:
    """获取防火墙状态信息"""
    status = run_firewall_cmd(["--state"])
    zones = run_firewall_cmd(["--get-zones"]).split()
    default_zone = run_firewall_cmd(["--get-default-zone"])
    
    return {
        "status": status,
        "default_zone": default_zone,
        "zones": zones
    }

@mcp.tool()
def list_ports(ctx: Context, zone: Optional[str] = None) -> Dict:
    """列出防火墙开放的端口"""
    cmd = ["--list-ports"]
    if zone:
        cmd.extend(["--zone", zone])
    
    ports = run_firewall_cmd(cmd).split()
    return {"ports": ports}

@mcp.tool()
def add_port(ctx: Context, port: str, protocol: str, zone: Optional[str] = None) -> str:
    """添加防火墙端口规则"""
    cmd = ["--add-port", f"{port}/{protocol}"]
    if zone:
        cmd.extend(["--zone", zone])
    cmd.append("--permanent")
    
    return run_firewall_cmd(cmd)

@mcp.tool()
def remove_port(ctx: Context, port: str, protocol: str, zone: Optional[str] = None) -> str:
    """删除防火墙端口规则"""
    cmd = ["--remove-port", f"{port}/{protocol}"]
    if zone:
        cmd.extend(["--zone", zone])
    cmd.append("--permanent")
    
    return run_firewall_cmd(cmd)

@mcp.tool()
def reload_firewall(ctx: Context) -> str:
    """重新加载防火墙配置"""
    return run_firewall_cmd(["--reload"])

if __name__ == "__main__":
    mcp.run()