#!/usr/bin/env python3
import subprocess
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("GCC Compiler Options Manager")

# GCC常用编译选项分类
GCC_OPTIONS = {
    "optimization": [
        {"name": "-O0", "description": "不优化(默认)"},
        {"name": "-O1", "description": "基本优化"},
        {"name": "-O2", "description": "更多优化"},
        {"name": "-O3", "description": "激进优化"},
        {"name": "-Os", "description": "优化代码大小"},
        {"name": "-Ofast", "description": "快速优化(可能违反标准)"}
    ],
    "warning": [
        {"name": "-Wall", "description": "启用所有常见警告"},
        {"name": "-Wextra", "description": "启用额外警告"},
        {"name": "-Werror", "description": "将警告视为错误"},
        {"name": "-w", "description": "禁用所有警告"}
    ],
    "debug": [
        {"name": "-g", "description": "生成调试信息"},
        {"name": "-ggdb", "description": "生成GDB专用调试信息"},
        {"name": "-g3", "description": "生成更多调试信息"}
    ],
    "language": [
        {"name": "-std=c89", "description": "C89标准"},
        {"name": "-std=c99", "description": "C99标准"},
        {"name": "-std=c11", "description": "C11标准"},
        {"name": "-std=c++98", "description": "C++98标准"},
        {"name": "-std=c++11", "description": "C++11标准"},
        {"name": "-std=c++14", "description": "C++14标准"},
        {"name": "-std=c++17", "description": "C++17标准"},
        {"name": "-std=c++20", "description": "C++20标准"}
    ],
    "other": [
        {"name": "-shared", "description": "生成共享库"},
        {"name": "-fPIC", "description": "位置无关代码"},
        {"name": "-pthread", "description": "支持多线程"},
        {"name": "-D", "description": "定义宏"},
        {"name": "-I", "description": "添加头文件搜索路径"},
        {"name": "-L", "description": "添加库文件搜索路径"},
        {"name": "-l", "description": "链接指定库"}
    ]
}

@mcp.tool()
def list_options(ctx: Context, category: Optional[str] = None) -> Dict:
    """列出GCC编译选项"""
    if category:
        if category in GCC_OPTIONS:
            return {category: GCC_OPTIONS[category]}
        return {"error": f"Invalid category: {category}"}
    return GCC_OPTIONS

@mcp.tool()
def compile(ctx: Context, source: str, options: List[str], output: Optional[str] = None) -> Dict:
    """使用指定选项编译源代码"""
    cmd = ["gcc", source]
    if output:
        cmd.extend(["-o", output])
    cmd.extend(options)
    
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        return {
            "status": "success",
            "output": result.stdout.strip(),
            "executable": output if output else "a.out"
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "error": e.stderr.strip()
        }

@mcp.tool()
def get_version(ctx: Context) -> str:
    """获取GCC版本信息"""
    try:
        result = subprocess.run(
            ["gcc", "--version"],
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout.split('\n')[0]
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

if __name__ == "__main__":
    mcp.run()