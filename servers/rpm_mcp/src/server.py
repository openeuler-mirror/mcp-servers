#!/usr/bin/env python3
import subprocess
import requests
from mcp.server.fastmcp import FastMCP

# 初始化 MCP
mcp = FastMCP("RPM MCP")

def run_cmd(cmd: list[str]):
    """执行命令并返回输出"""
    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {'stdout': output}
    except subprocess.CalledProcessError as e:
        return {
            'error': e,
            'output': e.output,
            'returncode': e.returncode
        }
    except Exception as e:
        return {'error': str(e)}


GITEE_API = "https://gitee.com/api/v5/repos/src-openeuler/{repo}/branches"

@mcp.tool()
def search_rpm_cross_repos(package_name: str) -> dict:
    """
    在openEuler上查询指定包名存在的os版本和分支，及最新commit信息

    Args:
        package_name: 主包名（如 nginx-mod 应考虑nginx）
    Returns:
        dict: 包含分支信息和最新的commit的提示
    """
    url = GITEE_API.format(repo=package_name)
    try:
        response = requests.get(url, params={"sort": "updated"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        return {
            "error": f"❌ Gitee API 请求失败: {e}",
            "hint": "如果你输入的是子包名，请确认是否需要查询主包 repo（例如 nginx 子包应查询 nginx 仓库）"
        }

    branches = response.json()
    if not branches:
        return {
            "result": f"未找到任何分支: {package_name}",
            "hint": "✅ 提示：openEuler 的一个仓库通常包含多个子包，如 nginx 的多个模块包都在 nginx 主仓内维护，请检查主包名是否正确。"
        }

    result = {}
    for b in branches:
        name = b.get("name", "")
        message = b.get("commit", {}).get("commit", {}).get("message", "")
        result[name] = message.strip() if message else "(无 commit message)"
    result["hint"] = f"✅ 提示：软件包仓库地址为 {url}"
    return result


@mcp.tool()
def list_installed():
    """列出所有已安装的 RPM 包"""
    return run_cmd(["rpm", "-qa"])

@mcp.tool()
def query_info(package: str):
    """查询指定包信息"""
    return run_cmd(["rpm", "-qi", package])

@mcp.tool()
def list_files(package: str):
    """列出包内包含哪些文件"""
    return run_cmd(["rpm", "-ql", package])

@mcp.tool()
def file_owner(filepath: str):
    """查询某个文件属于哪个包"""
    return run_cmd(["rpm", "-qf", filepath])

@mcp.tool()
def list_requires(package: str):
    """列出包的依赖"""
    return run_cmd(["rpm", "-qR", package])

@mcp.tool()
def verify_package(package: str):
    """验证包是否被修改"""
    output = run_cmd(["rpm", "-V", package])
    return output if output else "✅ 校验正常：无改动"

@mcp.tool()
def check_signature(rpm_file: str):
    """检查 RPM 文件签名"""
    return run_cmd(["rpm", "--checksig", rpm_file])

if __name__ == "__main__":
    mcp.run()