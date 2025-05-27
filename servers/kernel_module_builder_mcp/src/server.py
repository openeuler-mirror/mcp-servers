#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
import subprocess
import os
from pathlib import Path

mcp = FastMCP("kernel-module-builder")

def _run_command(cmd: list, cwd: Optional[str] = None) -> Dict[str, Any]:
    """执行命令并返回统一格式的结果"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Command failed: {e.stderr.strip()}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def build_module(
    source_path: str = Field(..., description="内核模块源代码路径"),
    module_name: str = Field(..., description="要构建的模块名称"),
    module_version: str = Field(default="1.0", description="模块版本号"),
    install: bool = Field(default=True, description="是否安装构建好的模块")
) -> Dict[str, Any]:
    """构建并安装内核模块
    
    示例用法:
    1. 构建并安装模块: build_module source_path=/path/to/module module_name=my_module
    2. 仅构建不安装: build_module source_path=/path/to/module module_name=my_module install=false
    3. 指定版本号: build_module source_path=/path/to/module module_name=my_module module_version=2.1

    使用DKMS进行构建和安装
    """
    if not os.path.isdir(source_path):
        return {"status": "error", "message": "Source path does not exist"}

    # 构建模块
    build_cmd = ["dkms", "build", "-m", module_name, "-v", module_version]
    build_result = _run_command(build_cmd, cwd=source_path)
    if build_result["status"] != "success":
        return build_result

    result = {"build_output": build_result["output"]}

    # 安装模块
    if install:
        install_cmd = ["dkms", "install", "-m", module_name, "-v", module_version]
        install_result = _run_command(install_cmd, cwd=source_path)
        if install_result["status"] != "success":
            return install_result
        result["install_output"] = install_result["output"]

    return {
        "status": "success",
        "message": "Module built" + (" and installed" if install else ""),
        **result
    }

@mcp.tool()
def list_modules(
    module_name: Optional[str] = Field(default=None, description="过滤条件: 模块名称")
) -> Dict[str, Any]:
    """列出系统中已安装的内核模块
    
    示例用法:
    1. 列出所有模块: list_modules
    2. 查询特定模块: list_modules module_name=my_module
    """
    cmd = ["dkms", "status"]
    if module_name:
        cmd.append(module_name)
    
    return _run_command(cmd)

@mcp.tool()
def remove_module(
    module_name: str = Field(..., description="要移除的模块名称"),
    module_version: str = Field(default="1.0", description="模块版本号"),
    purge: bool = Field(default=False, description="是否彻底清除模块(包括源代码)")
) -> Dict[str, Any]:
    """移除已安装的内核模块
    
    示例用法:
    1. 移除模块: remove_module module_name=my_module
    2. 彻底清除模块: remove_module module_name=my_module purge=true
    """
    cmd = ["dkms", "remove", "-m", module_name, "-v", module_version]
    if purge:
        cmd.append("--all")
    
    return _run_command(cmd)

if __name__ == "__main__":
    mcp.run()