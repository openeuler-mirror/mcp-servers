#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, List
from mcp.server.fastmcp import FastMCP
import subprocess
from pathlib import Path

mcp = FastMCP("text_processing_mcp")

@mcp.tool()
def sed_replace(
    input_text: str = Field(..., description="输入文本"),
    pattern: str = Field(..., description="sed替换模式，如's/old/new/g'"),
    in_place: bool = Field(default=False, description="是否直接修改原文件(当input_text为文件路径时)")
) -> Dict[str, str]:
    """使用sed进行文本替换
    
    示例用法:
    1. 替换文本中的字符串: input_text="hello world", pattern="s/world/China/g"
    2. 替换文件内容: input_text="/path/to/file", pattern="s/foo/bar/g", in_place=True
    """
    try:
        if in_place and Path(input_text).is_file():
            cmd = ["sed", "-i", pattern, input_text]
            subprocess.run(cmd, check=True)
            return {"status": "success", "message": f"File {input_text} modified"}
        else:
            result = subprocess.run(["sed", pattern], 
                                  input=input_text,
                                  capture_output=True, 
                                  text=True)
            return {"status": "success", "result": result.stdout}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def awk_process(
    input_text: str = Field(..., description="输入文本或文件路径"),
    script: str = Field(..., description="awk脚本命令"),
    file_input: bool = Field(default=False, description="输入是否为文件路径")
) -> Dict[str, str]:
    """使用awk处理文本
    
    示例用法:
    1. 提取第一列: script="{print $1}", input_text="a b c\nd e f"
    2. 处理文件: script="{print $2}", input_text="/path/to/file", file_input=True
    """
    try:
        if file_input:
            result = subprocess.run(["awk", script, input_text],
                                  capture_output=True, text=True)
        else:
            result = subprocess.run(["awk", script],
                                  input=input_text,
                                  capture_output=True, text=True)
        return {"status": "success", "result": result.stdout}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def grep_search(
    input_text: str = Field(..., description="输入文本或文件路径"),
    pattern: str = Field(..., description="搜索模式"),
    file_input: bool = Field(default=False, description="输入是否为文件路径"),
    options: str = Field(default="", description="grep选项如-i -v等")
) -> Dict[str, str]:
    """使用grep搜索文本
    
    示例用法:
    1. 搜索文本: input_text="hello\nworld", pattern="hello"
    2. 搜索文件: input_text="/path/to/file", pattern="error", file_input=True
    """
    try:
        args = ["grep"]
        if options:
            args.extend(options.split())
        args.append(pattern)
        
        if file_input:
            args.append(input_text)
            result = subprocess.run(args, capture_output=True, text=True)
        else:
            result = subprocess.run(args, input=input_text,
                                  capture_output=True, text=True)
        return {"status": "success", "matches": result.stdout.splitlines()}
    except subprocess.CalledProcessError:
        return {"status": "success", "matches": []}  # 没找到匹配项不算错误
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()