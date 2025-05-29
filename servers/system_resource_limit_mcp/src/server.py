import os
import subprocess
import shutil
from typing import List, Dict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("系统资源限制管理工具")
LIMITS_FILE = "/etc/security/limits.conf"
BACKUP_FILE = "/etc/security/limits.conf.bak"

def backup_limits_file():
    """备份limits.conf文件"""
    if not os.path.exists(BACKUP_FILE):
        shutil.copy2(LIMITS_FILE, BACKUP_FILE)

def parse_limits() -> List[Dict[str, str]]:
    """解析limits.conf文件内容"""
    limits = []
    if os.path.exists(LIMITS_FILE):
        with open(LIMITS_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 4:
                        limits.append({
                            'domain': parts[0],
                            'type': parts[1],
                            'item': parts[2],
                            'value': parts[3]
                        })
    return limits

def write_limits(limits: List[Dict[str, str]]):
    """写入limits.conf文件"""
    backup_limits_file()
    with open(LIMITS_FILE, 'w') as f:
        f.write("# This file is managed by MCP System Resource Limit Server\n")
        for limit in limits:
            f.write(f"{limit['domain']} {limit['type']} {limit['item']} {limit['value']}\n")

@mcp.tool()
def get_limits() -> List[Dict[str, str]]:
    """获取当前系统资源限制配置"""
    return parse_limits()

@mcp.tool()
def set_limits(domain: str, type: str, item: str, value: str) -> str:
    """设置指定域的资源限制"""
    limits = parse_limits()
    new_limits = [l for l in limits if not (l['domain'] == domain and l['item'] == item)]
    new_limits.append({
        'domain': domain,
        'type': type,
        'item': item,
        'value': value
    })
    write_limits(new_limits)
    return f"成功设置 {domain} 的 {item} 限制为 {value}"

@mcp.tool()
def add_limit(domain: str, type: str, item: str, value: str) -> str:
    """添加新的资源限制"""
    return set_limits(domain, type, item, value)

@mcp.tool()
def remove_limit(domain: str, item: str) -> str:
    """移除指定域的资源限制"""
    limits = parse_limits()
    new_limits = [l for l in limits if not (l['domain'] == domain and l['item'] == item)]
    write_limits(new_limits)
    return f"成功移除 {domain} 的 {item} 限制"

if __name__ == "__main__":
    mcp.run()