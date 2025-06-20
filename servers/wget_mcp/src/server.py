import os
import subprocess
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wget下载工具")

@mcp.tool()
def download_file(url: str, output_path: str = None) -> str:
    """下载指定URL的文件
    
    Args:
        url: 要下载的URL地址
        output_path: 输出的文件路径(可选)
        
    Returns:
        操作结果信息
    """
    try:
        cmd = ["wget", url]
        if output_path:
            cmd.extend(["-O", output_path])
        
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        
        if output_path:
            return f"成功下载文件到: {output_path}"
        else:
            filename = url.split('/')[-1]
            return f"成功下载文件: {filename}"
    except subprocess.CalledProcessError as e:
        return f"下载失败: {e.stderr or str(e)}"

if __name__ == "__main__":
    mcp.run()