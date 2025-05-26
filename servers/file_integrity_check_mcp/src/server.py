#!/usr/bin/env python3
from pydantic import Field
from typing import Optional
from mcp.server.fastmcp import FastMCP
import subprocess

# Initialize FastMCP server
mcp = FastMCP("file_integrity_check_mcp")

@mcp.tool()
def init_database(
    aide_config: Optional[str] = Field(default=None, description="AIDE配置文件路径"),
    tripwire_config: Optional[str] = Field(default=None, description="Tripwire配置文件路径")
) -> dict:
    """Initialize AIDE/Tripwire database
    
    示例用法:
    1. 使用默认配置初始化数据库
    2. 使用指定AIDE配置文件初始化: --aide-config /etc/aide/aide.conf
    3. 使用指定Tripwire配置文件初始化: --tripwire-config /etc/tripwire/tw.cfg
    
    返回:
    {
        "status": "success|error",
        "message": "执行结果描述",
        "aide_output": "AIDE输出(成功时)",
        "tripwire_output": "Tripwire输出(成功时)"
    }
    """
    try:
        # Initialize AIDE database
        aide_cmd = ["aide", "--init"]
        if aide_config:
            aide_cmd.extend(["--config", aide_config])
            
        aide_result = subprocess.run(aide_cmd, capture_output=True, text=True)

        # Initialize Tripwire database
        tripwire_cmd = ["tripwire", "--init"]
        if tripwire_config:
            tripwire_cmd.extend(["--cfgfile", tripwire_config])
            
        tripwire_result = subprocess.run(tripwire_cmd, capture_output=True, text=True)

        if aide_result.returncode == 0 and tripwire_result.returncode == 0:
            return {
                "status": "success",
                "message": "Databases initialized successfully",
                "aide_output": aide_result.stdout,
                "tripwire_output": tripwire_result.stdout
            }
        return {
            "status": "error",
            "message": f"AIDE: {aide_result.stderr}, Tripwire: {tripwire_result.stderr}"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def run_check(
    aide_config: Optional[str] = Field(default=None, description="AIDE配置文件路径"),
    tripwire_config: Optional[str] = Field(default=None, description="Tripwire配置文件路径")
) -> dict:
    """Run file integrity check
    
    示例用法:
    1. 使用默认配置运行检查
    2. 使用指定AIDE配置文件运行检查: --aide-config /etc/aide/aide.conf
    3. 使用指定Tripwire配置文件运行检查: --tripwire-config /etc/tripwire/tw.cfg
    
    返回:
    {
        "status": "success|error",
        "aide_output": "AIDE检查结果",
        "tripwire_output": "Tripwire检查结果"
    }
    """
    try:
        # Run AIDE check
        aide_cmd = ["aide", "--check"]
        if aide_config:
            aide_cmd.extend(["--config", aide_config])
            
        aide_result = subprocess.run(aide_cmd, capture_output=True, text=True)

        # Run Tripwire check
        tripwire_cmd = ["tripwire", "--check"]
        if tripwire_config:
            tripwire_cmd.extend(["--cfgfile", tripwire_config])
            
        tripwire_result = subprocess.run(tripwire_cmd, capture_output=True, text=True)

        return {
            "status": "success",
            "aide_output": aide_result.stdout,
            "tripwire_output": tripwire_result.stdout
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def view_report(
    aide_report_file: Optional[str] = Field(default=None, description="AIDE报告文件路径"),
    tripwire_report_file: Optional[str] = Field(default=None, description="Tripwire报告文件路径")
) -> dict:
    """View latest integrity check report
    
    示例用法:
    1. 查看最新报告
    2. 查看指定AIDE报告文件: --aide-report-file /var/lib/aide/aide.report
    3. 查看指定Tripwire报告文件: --tripwire-report-file /var/lib/tripwire/report/twr.txt
    
    返回:
    {
        "status": "success|error",
        "aide_report": "AIDE报告内容",
        "tripwire_report": "Tripwire报告内容"
    }
    """
    try:
        # Get AIDE report
        aide_cmd = ["aide", "--compare"]
        if aide_report_file:
            aide_cmd.extend(["--report", aide_report_file])
            
        aide_result = subprocess.run(aide_cmd, capture_output=True, text=True)

        # Get Tripwire report
        tripwire_cmd = ["tripwire", "--check"]
        if tripwire_report_file:
            tripwire_cmd.extend(["--twrfile", tripwire_report_file])
            
        tripwire_result = subprocess.run(tripwire_cmd, capture_output=True, text=True)

        return {
            "status": "success",
            "aide_report": aide_result.stdout,
            "tripwire_report": tripwire_result.stdout
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def update_database(
    aide_config: Optional[str] = Field(default=None, description="AIDE配置文件路径"),
    tripwire_config: Optional[str] = Field(default=None, description="Tripwire配置文件路径")
) -> dict:
    """Update integrity database
    
    示例用法:
    1. 更新数据库(根据最新检查结果)
    2. 使用指定AIDE配置文件更新: --aide-config /etc/aide/aide.conf
    3. 使用指定Tripwire配置文件更新: --tripwire-config /etc/tripwire/tw.cfg
    
    返回:
    {
        "status": "success|error",
        "message": "执行结果描述",
        "aide_output": "AIDE输出(成功时)",
        "tripwire_output": "Tripwire输出(成功时)"
    }
    """
    try:
        # Update AIDE database
        aide_cmd = ["aide", "--update"]
        if aide_config:
            aide_cmd.extend(["--config", aide_config])
            
        aide_result = subprocess.run(aide_cmd, capture_output=True, text=True)

        # Update Tripwire database
        tripwire_cmd = ["tripwire", "--update"]
        if tripwire_config:
            tripwire_cmd.extend(["--cfgfile", tripwire_config])
            
        tripwire_result = subprocess.run(tripwire_cmd, capture_output=True, text=True)

        if aide_result.returncode == 0 and tripwire_result.returncode == 0:
            return {
                "status": "success",
                "message": "Databases updated successfully",
                "aide_output": aide_result.stdout,
                "tripwire_output": tripwire_result.stdout
            }
        return {
            "status": "error",
            "message": f"AIDE: {aide_result.stderr}, Tripwire: {tripwire_result.stderr}"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()