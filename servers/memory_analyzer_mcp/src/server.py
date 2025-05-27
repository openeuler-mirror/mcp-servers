#!/usr/bin/env python3
from pydantic import Field
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import re
import os
import argparse
from pathlib import Path

mcp = FastMCP("memoryAnalyzerMcp")

@mcp.tool()
def valgrind_memcheck(
    program: str = Field(..., description="要检测的程序路径"),
    args: Optional[str] = Field(default="", description="程序参数"),
    options: Optional[str] = Field(default="", description="valgrind额外选项")
) -> Dict[str, Any]:
    """使用valgrind检测内存问题"""
    try:
        cmd = ['valgrind']
        if options:
            cmd.extend(options.split())
        cmd.append(program)
        if args:
            cmd.extend(args.split())
            
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        return {
            "status": "success",
            "report": output
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "report": e.output
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def asan_analyze(
    program: str = Field(..., description="要分析的程序路径"),
    args: Optional[str] = Field(default="", description="程序参数")
) -> Dict[str, Any]:
    """使用address-sanitizer分析内存错误"""
    try:
        env = os.environ.copy()
        env["ASAN_OPTIONS"] = "detect_leaks=1"
        
        cmd = [program]
        if args:
            cmd.extend(args.split())
            
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            env=env
        )
        return {
            "status": "success",
            "report": output
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "report": e.output
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def report_analyzer(
    report_file: str = Field(..., description="内存报告文件路径"),
    output_format: str = Field(default="text", description="输出格式(json/text)")
) -> Dict[str, Any]:
    """分析内存报告"""
    try:
        with open(report_file, 'r') as f:
            content = f.read()
            
        if output_format == "json":
            leaks = re.findall(r"definitely lost: (\d+) bytes", content)
            errors = re.findall(r"ERROR: AddressSanitizer: (\w+)", content)
            
            return {
                "status": "success",
                "report": {
                    "leaks": {
                        "count": len(leaks),
                        "total_bytes": sum(map(int, leaks)) if leaks else 0
                    },
                    "errors": errors
                }
            }
        else:
            return {
                "status": "success",
                "report": content
            }
    except Exception as e:
        return {"error": str(e)}

def init_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--VALGRIND_PATH', required=True, help="valgrind安装路径")
    parser.add_argument('--ASAN_OPTIONS', default="detect_leaks=1", help="ASAN配置选项")
    parser.add_argument('--REPORT_DIR',
                      default=str(Path.home() / ".local/share/memory_analyzer/reports"),
                      help="报告存储目录，默认为~/.local/share/memory_analyzer/reports")
    
    args = parser.parse_args()
    
    # 仅打印报告目录信息，不实际创建目录
    print(f"报告目录设置为: {args.REPORT_DIR} (不实际创建目录)")

if __name__ == "__main__":
    init_config()
    mcp.run()