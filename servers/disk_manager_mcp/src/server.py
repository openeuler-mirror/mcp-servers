#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, Any, List
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import os

mcp = FastMCP("disk_manager_mcp")

def _run_command(cmd: List[str], args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a shell command and return standardized result"""
    try:
        result = subprocess.run(
            cmd + args,
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
def df(
    path: Optional[str] = Field(default=None, description="Filesystem path to check"),
    human_readable: bool = Field(default=True, description="Show sizes in human readable format")
) -> Dict[str, Any]:
    """Show disk filesystem usage"""
    args = []
    if human_readable:
        args.append("-h")
    if path:
        args.append(path)
    
    return _run_command(["df"], args)

@mcp.tool()
def du(
    path: str = Field(..., description="Directory path to analyze"),
    human_readable: bool = Field(default=True, description="Show sizes in human readable format"),
    max_depth: Optional[int] = Field(default=None, description="Max directory depth to analyze")
) -> Dict[str, Any]:
    """Show directory space usage"""
    args = []
    if human_readable:
        args.append("-h")
    if max_depth is not None:
        args.extend(["--max-depth", str(max_depth)])
    args.append(path)
    
    return _run_command(["du"], args)

@mcp.tool()
def disk_usage(
    filesystem: Optional[str] = Field(default="/", description="Specific filesystem to query")
) -> Dict[str, Any]:
    """Get current disk usage information"""
    result = _run_command(["df", "-h", filesystem])
    if not result["success"]:
        return result
    
    # Parse df output
    lines = result["output"].split("\n")
    if len(lines) < 2:
        return {
            "success": False,
            "error": "Invalid df output format"
        }
    
    headers = lines[0].split()
    values = lines[1].split()
    return {
        "success": True,
        "data": dict(zip(headers, values))
    }

if __name__ == "__main__":
    mcp.run()