import os
import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("依赖分析工具")

def get_rpm_deps(package):
    """获取RPM包的依赖关系"""
    try:
        result = subprocess.run(
            ['rpm', '-q', '--requires', package],
            check=True, capture_output=True, text=True
        )
        return result.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

def get_dnf_deps(package):
    """使用DNF获取更详细的依赖关系"""
    try:
        result = subprocess.run(
            ['dnf', 'repoquery', '--requires', '--resolve', package],
            check=True, capture_output=True, text=True
        )
        return result.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

def get_pip_deps(package):
    """获取Python包的依赖关系"""
    try:
        result = subprocess.run(
            ['pip', 'show', package],
            check=True, capture_output=True, text=True
        )
        requires = []
        for line in result.stdout.splitlines():
            if line.startswith('Requires: '):
                requires = line.split(': ')[1].split(', ')
                break
        return requires if requires else []
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

@mcp.tool()
def analyze_rpm_deps(package: str) -> dict:
    """
    分析RPM包的依赖关系
    :param package: 要分析的RPM包名
    :return: 依赖关系(JSON格式)
    """
    rpm_deps = get_rpm_deps(package)
    dnf_deps = get_dnf_deps(package)
    
    return {
        "package": package,
        "rpm_dependencies": rpm_deps,
        "dnf_dependencies": dnf_deps
    }

@mcp.tool()
def analyze_pip_deps(package: str) -> dict:
    """
    分析Python pip包的依赖关系
    :param package: 要分析的Python包名
    :return: 依赖关系(JSON格式)
    """
    pip_deps = get_pip_deps(package)
    return {
        "package": package,
        "pip_dependencies": pip_deps
    }

if __name__ == "__main__":
    mcp.run()