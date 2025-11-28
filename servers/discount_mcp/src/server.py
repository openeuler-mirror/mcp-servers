"""
Discount MCP Server

面向 discount 软件包的命令行工具，包括：
- discount-makepage: Markdown 到 HTML 的转换工具
- discount-mkd2html: 带页眉页脚支持的 Markdown 转换工具  
- discount-theme: 带主题功能的 Markdown 转换工具
- markdown: 主要的 Markdown 处理工具

MCP tools 列表：
1. discount_makepage_version - 获取 discount-makepage 版本信息
2. discount_makepage_convert - 使用 discount-makepage 转换 Markdown 文件
3. discount_mkd2html_convert - 使用 discount-mkd2html 转换 Markdown 文件（支持页眉页脚）
4. discount_theme_version - 获取 discount-theme 版本信息
5. discount_theme_convert - 使用 discount-theme 转换 Markdown 文件（支持主题）
6. markdown_version - 获取 markdown 命令版本信息
7. markdown_convert_basic - 基本的 Markdown 文件转换
8. markdown_convert_advanced - 高级 Markdown 文件转换（支持输出文件等）
9. markdown_convert_string - 转换 Markdown 字符串（非文件）

所有工具返回统一的 JSON 结构：
{
  "success": bool,
  "command": str,
  "exit_code": int,
  "stdout": str,
  "stderr": str
}
"""

from mcp.server.fastmcp import FastMCP, Context
import subprocess
import json
from typing import List, Optional

mcp = FastMCP("Discount MCP Server")

@mcp.tool()
def discount_makepage_version() -> dict:
    """
    获取 discount-makepage 命令的版本信息
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["discount-makepage", "--version"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def discount_makepage_convert(input_file: str, flags: Optional[str] = None, output_links: bool = False) -> dict:
    """
    使用 discount-makepage 将 Markdown 文件转换为 HTML
    
    参数:
        input_file: 输入的 Markdown 文件路径
        flags: 可选的处理标志（如 "-f", "-flags" 等）
        output_links: 是否输出链接信息
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["discount-makepage"]
    
    if flags:
        cmd.append(flags)
    
    if output_links:
        cmd.append("-links")
    
    cmd.append(input_file)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def discount_mkd2html_convert(input_file: str, header: Optional[str] = None, footer: Optional[str] = None, css: Optional[str] = None) -> dict:
    """
    使用 discount-mkd2html 将 Markdown 文件转换为 HTML，支持添加页眉、页脚和 CSS
    
    参数:
        input_file: 输入的 Markdown 文件路径
        header: 可选的页眉内容文件路径
        footer: 可选的页脚内容文件路径  
        css: 可选的 CSS 样式文件路径
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["discount-mkd2html"]
    
    if header:
        cmd.extend(["-header", header])
    
    if footer:
        cmd.extend(["-footer", footer])
    
    if css:
        cmd.extend(["-css", css])
    
    cmd.append(input_file)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def discount_theme_version() -> dict:
    """
    获取 discount-theme 命令的版本信息
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["discount-theme", "-V"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def discount_theme_convert(input_file: str, output_file: Optional[str] = None, flags: Optional[str] = None, 
                          css_file: Optional[str] = None, prefix: Optional[str] = None) -> dict:
    """
    使用 discount-theme 将 Markdown 文件转换为 HTML，支持主题功能
    
    参数:
        input_file: 输入的 Markdown 文件路径
        output_file: 可选的输出文件路径（使用 -o 参数）
        flags: 可选的处理标志（如 "-f", "-C", "-E" 等）
        css_file: 可选的 CSS 主题文件路径（使用 -t 参数）
        prefix: 可选的前缀内容（使用 -p 参数）
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["discount-theme"]
    
    if flags:
        cmd.append(flags)
    
    if css_file:
        cmd.extend(["-t", css_file])
    
    if prefix:
        cmd.extend(["-p", prefix])
    
    if output_file:
        cmd.extend(["-o", output_file])
    
    cmd.append(input_file)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def markdown_version() -> dict:
    """
    获取 markdown 命令的版本信息
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["markdown", "--version"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def markdown_convert_basic(input_file: str, base_url: Optional[str] = None, debug: bool = False, 
                          no_links: bool = False, style: bool = False) -> dict:
    """
    使用 markdown 命令进行基本的 Markdown 文件转换
    
    参数:
        input_file: 输入的 Markdown 文件路径
        base_url: 可选的基础 URL（使用 -b 参数）
        debug: 是否启用调试模式
        no_links: 是否禁用链接处理
        style: 是否包含样式信息
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["markdown"]
    
    if base_url:
        cmd.extend(["-b", base_url])
    
    if debug:
        cmd.append("-d")
    
    if no_links:
        cmd.append("-n")
    
    if style:
        cmd.append("-S")
    
    cmd.append(input_file)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def markdown_convert_advanced(input_file: str, output_file: Optional[str] = None, html5: bool = False,
                            toc: bool = False, encoding: Optional[str] = None) -> dict:
    """
    使用 markdown 命令进行高级 Markdown 文件转换
    
    参数:
        input_file: 输入的 Markdown 文件路径
        output_file: 可选的输出文件路径（使用 -o 参数）
        html5: 是否使用 HTML5 输出格式
        toc: 是否生成目录
        encoding: 可选的编码设置（使用 -E 参数）
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["markdown"]
    
    if output_file:
        cmd.extend(["-o", output_file])
    
    if html5:
        cmd.append("-html5")
    
    if toc:
        cmd.append("-toc")
    
    if encoding:
        cmd.extend(["-E", encoding])
    
    cmd.append(input_file)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

@mcp.tool()
def markdown_convert_string(markdown_text: str, text_mode: bool = False) -> dict:
    """
    使用 markdown 命令直接转换 Markdown 字符串（而不是文件）
    
    参数:
        markdown_text: 要转换的 Markdown 文本内容
        text_mode: 是否使用文本模式（-t 参数）
    
    返回:
        dict: 包含命令执行结果的统一 JSON 结构
    """
    cmd = ["markdown"]
    
    if text_mode:
        cmd.append("-t")
    else:
        cmd.append("-s")
    
    try:
        result = subprocess.run(cmd, input=markdown_text, capture_output=True, text=True, timeout=30)
        return {
            "success": result.returncode == 0,
            "command": f"{' '.join(cmd)} '{markdown_text}'",
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "command": f"{' '.join(cmd)} '{markdown_text}'",
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e)
        }

if __name__ == "__main__":
    mcp.run()