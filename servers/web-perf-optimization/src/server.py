#!/usr/bin/env python3
from pydantic import Field
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import argparse
import os
from pathlib import Path
import requests

mcp = FastMCP("webPerfOptimization")

@mcp.tool()
def analyze_with_lighthouse(
    url: str = Field(..., description="要分析的网页URL"),
    output_format: str = Field(default="json", description="输出格式(json/html)"),
    device: str = Field(default="desktop", description="模拟设备类型(desktop/mobile)"),
    quiet: bool = Field(default=True, description="减少控制台输出")
) -> Dict[str, Any]:
    """使用Lighthouse分析网页性能
    
    示例用法:
    1. 分析https://example.com: analyze_with_lighthouse url=https://example.com
    2. 生成HTML报告: analyze_with_lighthouse url=https://example.com output_format=html
    3. 模拟移动设备: analyze_with_lighthouse url=https://example.com device=mobile
    """
    cmd = ["lighthouse", url]
    
    if output_format:
        cmd.extend(["--output", output_format])
    
    if device:
        cmd.extend(["--emulated-form-factor", device])
    
    if quiet:
        cmd.append("--quiet")
    
    cmd.append("--output-path=stdout")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        if output_format == "json":
            return {
                "success": True,
                "data": json.loads(result.stdout)
            }
        else:
            return {
                "success": True,
                "report": result.stdout
            }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": e.stderr.strip()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
def analyze_with_pagespeed(
    url: str = Field(..., description="要分析的网页URL"),
    strategy: str = Field(default="desktop", description="分析策略(desktop/mobile)"),
    api_key: Optional[str] = Field(default=None, description="Google API密钥(可选)")
) -> Dict[str, Any]:
    """使用PageSpeed Insights API分析网页性能
    
    示例用法:
    1. 分析https://example.com: analyze_with_pagespeed url=https://example.com
    2. 使用移动策略: analyze_with_pagespeed url=https://example.com strategy=mobile
    """
    api_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": url,
        "strategy": strategy
    }
    
    if api_key:
        params["key"] = api_key
    
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        return {
            "success": True,
            "data": response.json()
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
def get_performance_metrics(
    url: str = Field(..., description="要分析的网页URL"),
    tool: str = Field(default="lighthouse", description="分析工具(lighthouse/pagespeed)")
) -> Dict[str, Any]:
    """获取网页性能指标
    
    示例用法:
    1. 使用Lighthouse分析: get_performance_metrics url=https://example.com
    2. 使用PageSpeed分析: get_performance_metrics url=https://example.com tool=pagespeed
    """
    if tool == "lighthouse":
        return analyze_with_lighthouse(url=url)
    elif tool == "pagespeed":
        return analyze_with_pagespeed(url=url)
    else:
        return {
            "success": False,
            "error": f"不支持的工具: {tool}"
        }

def init_config():
    """初始化配置"""
    # 检查lighthouse是否安装
    try:
        subprocess.run(["lighthouse", "--version"], check=True)
    except Exception:
        print("警告: lighthouse未安装，请先运行'npm install -g lighthouse'")

if __name__ == "__main__":
    init_config()
    mcp.run()