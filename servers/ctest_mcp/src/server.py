#!/usr/bin/env python3
# 标准库导入
import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# 第三方库导入
from pydantic import Field

# 本地模块导入
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ctestMcp")

@mcp.tool()
def run_tests(
    build_dir: str = Field(..., description="CMake构建目录路径"),
    tests: Optional[List[str]] = Field(default=None, description="要运行的测试名称列表(默认运行所有)"),
    parallel: Optional[int] = Field(default=None, description="并行测试数量"),
    output_on_failure: bool = Field(default=True, description="测试失败时显示输出"),
    verbose: bool = Field(default=False, description="详细输出模式"),
    timeout: Optional[int] = Field(default=None, description="单个测试超时时间(秒)")
) -> Dict[str, Any]:
    """运行CMake测试套件
    
    示例用法:
    1. 运行所有测试: run_tests build_dir=/path/to/build
    2. 运行特定测试: run_tests build_dir=/path/to/build tests=["test1","test2"]
    3. 并行运行测试: run_tests build_dir=/path/to/build parallel=4
    """
    cmd = ["ctest", "--test-dir", build_dir]
    
    if tests:
        cmd.extend(["-R", "|".join(tests)])
    
    if parallel:
        cmd.extend(["-j", str(parallel)])
    
    if output_on_failure:
        cmd.append("--output-on-failure")
    
    if verbose:
        cmd.append("-VV")
    
    if timeout:
        cmd.extend(["--timeout", str(timeout)])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # 测试失败时返回非零状态码
        )
        
        return {
            "success": True,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
            "exit_code": result.returncode
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
def list_tests(
    build_dir: str = Field(..., description="CMake构建目录路径"),
    verbose: bool = Field(default=False, description="显示详细测试信息")
) -> Dict[str, Any]:
    """列出所有可用测试
    
    示例用法:
    1. 列出测试: list_tests build_dir=/path/to/build
    2. 详细列表: list_tests build_dir=/path/to/build verbose=true
    """
    cmd = ["ctest", "--test-dir", build_dir, "-N"]
    
    if verbose:
        cmd.append("-V")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {"success": True, "output": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": e.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def test_coverage(
    build_dir: str = Field(..., description="CMake构建目录路径"),
    output_file: Optional[str] = Field(default=None, description="覆盖率输出文件路径")
) -> Dict[str, Any]:
    """生成测试覆盖率报告
    
    示例用法:
    1. 生成覆盖率: test_coverage build_dir=/path/to/build
    2. 指定输出文件: test_coverage build_dir=/path/to/build output_file=coverage.xml
    """
    cmd = ["ctest", "--test-dir", build_dir, "-T", "Coverage"]
    
    if output_file:
        cmd.extend(["--output", output_file])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # 覆盖率可能返回非零状态码
        )
        return {
            "success": True,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
            "exit_code": result.returncode
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def init_config():
    """初始化配置"""
    # 这里可以添加服务初始化逻辑
    pass

if __name__ == "__main__":
    init_config()
    mcp.run()