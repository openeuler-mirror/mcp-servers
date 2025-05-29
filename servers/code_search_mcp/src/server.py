import os
import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("代码搜索工具")

def format_rg_output(output):
    """格式化ripgrep输出为结构化数据"""
    results = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split(':', 2)
        if len(parts) >= 3:
            results.append({
                "file": parts[0],
                "line": parts[1],
                "content": parts[2]
            })
    return results

@mcp.tool()
def search_code(search_term: str, path: str = ".", file_type: str = None) -> dict:
    """
    在指定路径下搜索代码
    :param search_term: 要搜索的内容
    :param path: 搜索路径(默认为当前目录)
    :param file_type: 文件类型过滤(如.py,.js等)
    :return: 搜索结果(JSON格式)
    """
    if not os.path.exists(path):
        return {"error": f"路径 {path} 不存在"}
    
    cmd = ["rg", "--no-heading", "--color=never", search_term, path]
    if file_type:
        cmd.extend(["-t", file_type])
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return {
            "results": format_rg_output(result.stdout),
            "stats": {
                "matches": len(result.stdout.splitlines()),
                "command": " ".join(cmd)
            }
        }
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:  # rg返回1表示没有匹配项
            return {"results": [], "stats": {"matches": 0}}
        return {"error": str(e), "output": e.stdout}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    mcp.run()