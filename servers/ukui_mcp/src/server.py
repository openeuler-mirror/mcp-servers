from mcp.server.fastmcp import FastMCP
import subprocess
import os
import psutil
from typing import Literal
import xml.etree.ElementTree as ET
from urllib.parse import unquote

# 创建MCP服务器，命名为 UKUI 助手
mcp = FastMCP("UKUI桌面助手")

@mcp.tool()
def get_active_window() -> str:
    """
    获取当前UKUI桌面正在使用的活动窗口标题
    注意：需要提前安装xdotool
    
    Returns:
        str:窗口标题或错误信息
    """
    try:
        cmd = ["xdotool", "getactivewindow", "getwindowname"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"当前正在使用: {result.stdout.strip()}"
    except Exception:
        return "获取活动窗口失败，请确认是否安装了xdotool"

@mcp.tool()
def get_recent_documents(limit: int = 5) -> list[str]:
    """
    读取UKUI/XDG标准的最近打开文件记录
    让AI了解最近处理的文档、图片或项目
    
    Args:
        limit:返回的最近文件数量限制，默认5个
    Returns:
        list[str]:最近打开的文件路径列表
    """
    recent_file_path = os.path.expanduser("~/.local/share/recently-used.xbel")
    if not os.path.exists(recent_file_path):
        return ["目前没有最近使用的文件记录。"]

    try:
        tree = ET.parse(recent_file_path)
        root = tree.getroot()
        files = []
        for bookmark in reversed(root.findall(".//{http://www.freedesktop.org/standards/desktop-bookmarks}bookmark")):
            href = bookmark.get("href")
            if href and href.startswith("file://"):
                files.append(unquote(href[7:]))
            if len(files) >= limit:
                break
        return files
    except Exception as e:
        return [f"读取最近文件失败: {str(e)}"]

@mcp.tool()
def set_ukui_wallpaper(image_path: str) -> str:
    """
    UKUI壁纸更改工具(与GNOME兼容)
    
    Args:
        image_path:图片的绝对路径
    Returns:
        str:设置结果消息
    """
    schema = "org.gnome.desktop.background"
    key = "picture-uri"
    
    if not os.path.isfile(image_path):
        return f"失败：文件无效"
    
    try:
        subprocess.run(['gsettings', 'set', schema, key, image_path], check=True,timeout=10)
        return f"设置成功，壁纸已设置为: {image_path}"
    except Exception as e:
        return f"设置失败：{str(e)}"

def main():
    mcp.run()

if __name__ == "__main__":
    main()