#!/usr/bin/env python3
import subprocess
import json
from typing import Dict, Optional
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("入侵检测系统")

def run_aide_command(args: list) -> str:
    """执行aide命令并返回结果"""
    try:
        result = subprocess.run(
            ["aide"] + args,
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"
    except FileNotFoundError:
        return "Error: aide命令未安装，请先安装aide工具"

@mcp.tool()
def check_aide_installed(ctx: Context) -> Dict:
    """检查aide是否已安装"""
    try:
        subprocess.run(["aide", "--version"], check=True, capture_output=True)
        return {"installed": True, "message": "aide已安装"}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"installed": False, "message": "aide未安装"}

@mcp.tool()
def initialize_aide(ctx: Context) -> str:
    """初始化aide数据库"""
    return run_aide_command(["--init"])

@mcp.tool() 
def perform_scan(ctx: Context) -> str:
    """执行入侵检测扫描"""
    return run_aide_command(["--check"])

@mcp.tool()
def update_aide_db(ctx: Context) -> str:
    """更新aide数据库"""
    return run_aide_command(["--update"])

@mcp.tool()
def get_scan_results(ctx: Context, file_path: Optional[str] = None) -> Dict:
    """获取扫描结果"""
    if file_path:
        try:
            with open(file_path, 'r') as f:
                return {"results": f.read()}
        except IOError as e:
            return {"error": str(e)}
    else:
        return {"message": "请指定扫描结果文件路径"}

@mcp.tool()
def configure_rule(ctx: Context, rule: str) -> str:
    """配置IDS规则"""
    try:
        with open("/etc/aide/aide.conf", "a") as f:
            f.write(f"\n{rule}\n")
        return "规则添加成功"
    except IOError as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()