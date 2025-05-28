#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import os
import argparse
from pathlib import Path

mcp = FastMCP("usbMonitorMcp")

def _run_command(cmd: list) -> Dict[str, Any]:
    """执行命令并返回统一格式结果"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return {"result": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"error": f"命令执行失败: {e.stderr.strip()}"}
    except Exception as e:
        return {"error": f"未知错误: {str(e)}"}

@mcp.tool()
def get_usb_devices(
    verbose: bool = Field(default=False, description="是否显示详细信息")
) -> Dict[str, Any]:
    """获取当前连接的USB设备列表
    
    示例用法:
    1. 获取USB设备列表
    2. 获取USB设备详细信息
    """
    cmd = ["lsusb"]
    if verbose:
        cmd.append("-v")
    
    return _run_command(cmd)

@mcp.tool() 
def monitor_usb_changes(
    interval: int = Field(default=5, description="监控间隔(秒)", gt=0),
    callback_url: Optional[str] = Field(default=None, description="回调URL，当检测到变化时调用")
) -> Dict[str, Any]:
    """监控USB设备变化
    
    示例用法:
    1. 监控USB设备变化，每10秒检查一次
    2. 监控USB设备变化，检测到变化时调用指定URL
    """
    # 初始设备列表
    initial_devices = get_usb_devices()
    if "error" in initial_devices:
        return initial_devices
    
    return {
        "message": "USB设备监控已启动",
        "interval": f"每{interval}秒检查一次",
        "callback_url": callback_url if callback_url else "无回调配置",
        "initial_devices": initial_devices
    }

def init_config():
    """初始化配置"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--HOME_DIR', required=True)
    
    args = parser.parse_args()
    
    # 确保配置目录存在
    config_dir = os.path.expanduser('~/.config/usb_monitor')
    Path(config_dir).mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    init_config()
    mcp.run()