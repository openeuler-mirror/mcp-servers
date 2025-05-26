#!/usr/bin/env python3
from pydantic import Field
from typing import Dict, Any, Optional, List
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import argparse
import os
from pathlib import Path

mcp = FastMCP("filesystemRepairMcp")

@mcp.tool()
def fsck(
    device: str = Field(..., description="要检查的设备路径(如/dev/sda1)"),
    fs_type: Optional[str] = Field(default=None, description="文件系统类型(如ext4,xfs)"),
    force: bool = Field(default=False, description="强制检查即使文件系统看起来正常"),
    interactive: bool = Field(default=False, description="交互式模式(默认自动修复)"),
    repair: bool = Field(default=True, description="自动修复发现的错误"),
    verbose: bool = Field(default=False, description="详细输出模式")
) -> Dict[str, Any]:
    """执行文件系统检查与修复
    
    示例用法:
    1. 检查/dev/sda1文件系统: fsck device=/dev/sda1
    2. 强制检查ext4文件系统: fsck device=/dev/sdb1 fs_type=ext4 force=true
    3. 交互式检查: fsck device=/dev/sdc1 interactive=true
    """
    cmd = ["fsck"]
    
    if fs_type:
        cmd.extend(["-t", fs_type])
    
    if force:
        cmd.append("-f")
    
    if not interactive:
        cmd.append("-y")  # 自动回答yes
    else:
        cmd.append("-n")  # 非交互式模式下不自动修复
    
    if verbose:
        cmd.append("-v")
    
    cmd.append(device)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # fsck可能返回非零状态码
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
def mount(
    device: str = Field(..., description="要挂载的设备路径"),
    mountpoint: str = Field(..., description="挂载点目录路径"),
    fs_type: Optional[str] = Field(default=None, description="文件系统类型"),
    options: Optional[List[str]] = Field(default=None, description="挂载选项列表")
) -> Dict[str, Any]:
    """挂载文件系统
    
    示例用法:
    1. 挂载/dev/sda1到/mnt: mount device=/dev/sda1 mountpoint=/mnt
    2. 指定文件系统类型: mount device=/dev/sdb1 mountpoint=/data fs_type=xfs
    3. 使用特定选项: mount device=/dev/sdc1 mountpoint=/backup options=ro,noexec
    """
    cmd = ["mount"]
    
    if fs_type:
        cmd.extend(["-t", fs_type])
    
    if options:
        cmd.extend(["-o", ",".join(options)])
    
    cmd.extend([device, mountpoint])
    
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
def umount(
    target: str = Field(..., description="要卸载的设备路径或挂载点"),
    force: bool = Field(default=False, description="强制卸载"),
    lazy: bool = Field(default=False, description="延迟卸载")
) -> Dict[str, Any]:
    """卸载文件系统
    
    示例用法:
    1. 卸载/mnt: umount target=/mnt
    2. 强制卸载: umount target=/dev/sda1 force=true
    3. 延迟卸载: umount target=/data lazy=true
    """
    cmd = ["umount"]
    
    if force:
        cmd.append("-f")
    
    if lazy:
        cmd.append("-l")
    
    cmd.append(target)
    
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
def check_disk_space(
    path: str = Field(default="/", description="要检查的路径"),
    human_readable: bool = Field(default=True, description="以人类可读格式显示")
) -> Dict[str, Any]:
    """检查磁盘空间使用情况
    
    示例用法:
    1. 检查根分区: check_disk_space
    2. 检查/data分区: check_disk_space path=/data
    3. 原始数据输出: check_disk_space human_readable=false
    """
    cmd = ["df"]
    
    if human_readable:
        cmd.append("-h")
    
    cmd.append(path)
    
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
def repair_filesystem(
    device: str = Field(..., description="要修复的设备路径"),
    fs_type: str = Field(..., description="文件系统类型"),
    backup_superblock: bool = Field(default=True, description="使用备份超级块修复"),
    interactive: bool = Field(default=False, description="交互式模式")
) -> Dict[str, Any]:
    """高级文件系统修复工具
    
    示例用法:
    1. 修复ext4文件系统: repair_filesystem device=/dev/sda1 fs_type=ext4
    2. 不使用备份超级块: repair_filesystem device=/dev/sdb1 fs_type=xfs backup_superblock=false
    3. 交互式修复: repair_filesystem device=/dev/sdc1 fs_type=ext4 interactive=true
    """
    if fs_type == "ext4":
        cmd = ["fsck.ext4"]
    elif fs_type == "xfs":
        cmd = ["xfs_repair"]
    else:
        return {"success": False, "error": f"不支持的文件系统类型: {fs_type}"}
    
    if fs_type == "ext4" and backup_superblock:
        # 查找备份超级块
        try:
            result = subprocess.run(
                ["dumpe2fs", device],
                capture_output=True,
                text=True,
                check=True
            )
            # 解析输出获取备份超级块位置
            for line in result.stdout.splitlines():
                if "Backup superblock at" in line:
                    backup_sb = line.split()[-1]
                    cmd.extend(["-b", backup_sb])
                    break
        except Exception:
            pass
    
    if not interactive:
        cmd.append("-y")
    
    cmd.append(device)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
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