import os
import subprocess
import json
from typing import List, Dict, Optional
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("代码审查助手")

def detect_language(file_path: str) -> Optional[str]:
    """根据文件扩展名检测编程语言"""
    ext = Path(file_path).suffix.lower()
    if ext in ('.c', '.cpp', '.h', '.hpp'):
        return 'c_cpp'
    elif ext == '.py':
        return 'python'
    return None

def run_cppcheck(file_path: str) -> Dict:
    """运行cppcheck分析C/C++代码"""
    try:
        result = subprocess.run(
            ['cppcheck', '--enable=all', '--output-file=-', file_path],
            check=True, capture_output=True, text=True
        )
        return {
            "tool": "cppcheck",
            "output": result.stdout,
            "errors": result.stderr
        }
    except subprocess.CalledProcessError as e:
        return {
            "tool": "cppcheck",
            "error": str(e),
            "output": e.stdout,
            "errors": e.stderr
        }

def run_pylint(file_path: str) -> Dict:
    """运行pylint分析Python代码"""
    try:
        result = subprocess.run(
            ['pylint', '--output-format=json', file_path],
            check=True, capture_output=True, text=True
        )
        return {
            "tool": "pylint",
            "output": json.loads(result.stdout),
            "errors": result.stderr
        }
    except subprocess.CalledProcessError as e:
        return {
            "tool": "pylint",
            "error": str(e),
            "output": e.stdout,
            "errors": e.stderr
        }

def analyze_file(file_path: str) -> Dict:
    """分析单个代码文件"""
    if not os.path.exists(file_path):
        return {"error": f"文件 {file_path} 不存在"}
    
    language = detect_language(file_path)
    if not language:
        return {"error": f"不支持的文件类型 {Path(file_path).suffix}"}
    
    if language == 'c_cpp':
        return run_cppcheck(file_path)
    elif language == 'python':
        return run_pylint(file_path)

def analyze_directory(dir_path: str) -> Dict:
    """分析目录中的所有代码文件"""
    if not os.path.isdir(dir_path):
        return {"error": f"目录 {dir_path} 不存在"}
    
    results = {}
    for root, _, files in os.walk(dir_path):
        for file in files:
            file_path = os.path.join(root, file)
            language = detect_language(file_path)
            if language:
                results[file_path] = analyze_file(file_path)
    
    return results

@mcp.tool()
def analyze_code(file_path: str) -> Dict:
    """
    静态分析指定代码文件
    :param file_path: 要分析的文件路径
    :return: 分析结果(JSON格式)
    """
    return analyze_file(file_path)

@mcp.tool()
def analyze_project(dir_path: str) -> Dict:
    """
    分析整个项目目录的代码
    :param dir_path: 项目目录路径
    :return: 分析结果(JSON格式)
    """
    return analyze_directory(dir_path)

if __name__ == "__main__":
    mcp.run()