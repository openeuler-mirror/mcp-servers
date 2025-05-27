#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, List
from mcp.server.fastmcp import FastMCP
import subprocess
from pathlib import Path
import json

mcp = FastMCP("system_log_manager_mcp")

@mcp.tool()
def configure_logrotate(
    log_file: str = Field(..., description="要配置轮转的日志文件路径"),
    options: str = Field(..., description="logrotate配置选项")
) -> Dict[str, str]:
    """Configure log rotation for specified log file
    
    示例用法:
    1. 为/var/log/nginx/access.log配置日志轮转: 
       maxsize 100M, daily rotate, keep 7 days
    2. 为/var/log/myapp.log配置日志轮转:
       weekly, missingok, rotate 4
    """
    config = f"""{log_file} {{
    {options}
}}"""
    
    try:
        with open(f"/etc/logrotate.d/{Path(log_file).name}", "w") as f:
            f.write(config)
        return {"status": "success", "message": f"Logrotate configured for {log_file}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def list_logs() -> Dict[str, List[str]]:
    """List system log files
    
    示例用法:
    1. 列出/var/log目录下所有日志文件
    """
    try:
        result = subprocess.run(["ls", "/var/log"], 
                              capture_output=True, text=True)
        return {"status": "success", "logs": result.stdout.splitlines()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def view_log(
    log_path: str = Field(..., description="要查看的日志文件路径"),
    lines: int = Field(default=100, description="要查看的行数")
) -> Dict[str, str]:
    """View log file contents
    
    示例用法:
    1. 查看/var/log/syslog的最后100行
    2. 查看/var/log/nginx/error.log的最后50行
    """
    try:
        result = subprocess.run(["tail", f"-n{lines}", log_path],
                              capture_output=True, text=True)
        return {"status": "success", "content": result.stdout}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()