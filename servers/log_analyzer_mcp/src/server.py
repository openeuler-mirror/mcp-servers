#!/usr/bin/env python3
from pydantic import Field
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import sys

mcp = FastMCP("logAnalyzerMcp")

class LogAnalyzerMcp:
    @staticmethod
    def run_command(cmd: str, args: list) -> Dict[str, Any]:
        """Execute a shell command and return the result"""
        try:
            result = subprocess.run(
                [cmd] + args,
                capture_output=True,
                text=True,
                check=True
            )
            return {
                "success": True,
                "output": result.stdout.strip(),
                "error": result.stderr.strip()
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "output": e.stdout.strip(),
                "error": e.stderr.strip()
            }

@mcp.tool()
def analyze_syslog(
    keyword: Optional[str] = Field(default=None, description="搜索关键词"),
    since: Optional[str] = Field(default=None, description="起始时间"),
    service: Optional[str] = Field(default=None, description="服务名称")
) -> Dict[str, Any]:
    """分析/var/log/messages日志"""
    args = []
    if keyword:
        args.extend(["|", "grep", keyword])
    if since:
        args.extend(["|", "awk", f'-v since="{since}"', '"$1 >= since"'])
    if service:
        args.extend(["|", "grep", service])
    
    cmd = f"cat /var/log/messages {' '.join(args)}" if args else "cat /var/log/messages"
    return LogAnalyzerMcp.run_command("bash", ["-c", cmd])

@mcp.tool()
def query_journal(
    unit: Optional[str] = Field(default=None, description="systemd单元"),
    priority: Optional[str] = Field(default=None, description="日志级别"),
    since: Optional[str] = Field(default=None, description="起始时间"),
    until: Optional[str] = Field(default=None, description="结束时间")
) -> Dict[str, Any]:
    """查询systemd journal日志"""
    args = ["-o", "json"]
    if unit:
        args.extend(["-u", unit])
    if priority:
        args.extend(["-p", priority])
    if since:
        args.extend(["--since", since])
    if until:
        args.extend(["--until", until])
    
    return LogAnalyzerMcp.run_command("journalctl", args)

@mcp.tool()
def log_stats(
    time_range: str = Field(..., description="时间范围(如'1h','24h')")
) -> Dict[str, Any]:
    """获取日志统计信息"""
    journal_cmd = ["journalctl", "--since", time_range, "--no-pager"]
    syslog_cmd = ["bash", "-c", f"grep '$(date -d \"{time_range} ago\" +\"%b %-d %H:%M\")' /var/log/messages"]
    
    journal_result = LogAnalyzerMcp.run_command(journal_cmd[0], journal_cmd[1:])
    syslog_result = LogAnalyzerMcp.run_command(syslog_cmd[0], syslog_cmd[1:])
    
    if not journal_result["success"] or not syslog_result["success"]:
        return {
            "success": False,
            "error": "Failed to get log statistics"
        }
    
    return {
        "success": True,
        "data": {
            "journal_entries": len(journal_result["output"].split("\n")) if journal_result["output"] else 0,
            "syslog_entries": len(syslog_result["output"].split("\n")) if syslog_result["output"] else 0
        }
    }

if __name__ == "__main__":
    mcp.run()