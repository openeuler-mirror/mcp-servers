#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP
from typing import Literal
import subprocess
import os

# 创建MCP服务器
mcp = FastMCP("GNOME Wallpaper Changer")

@mcp.tool()
def change_wallpaper(
    wallpaper: str
) -> str:
    """
    更改GNOME桌面壁纸
    
    Args:
        wallpaper: 壁纸文件路径或预设名称('default', 'nature', 'abstract'等)
    
    Returns:
        str: 要执行的gsettings命令
    """
    # 预设壁纸映射
    presets = {
        'default': '/usr/share/backgrounds/default.jpg',
        'nature': '/usr/share/backgrounds/night.jpg',
        'abstract': '/usr/share/backgrounds/day.jpg'
    }
    
    # 检查是否是预设名称
    actual_path = presets.get(wallpaper, wallpaper)
    
    # 返回要执行的命令
    return f"gsettings set org.gnome.desktop.background picture-uri file://{actual_path}"

if __name__ == "__main__":
    mcp.run()