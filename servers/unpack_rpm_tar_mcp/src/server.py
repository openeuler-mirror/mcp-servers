import tarfile
import os
import subprocess
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tar压缩和解压工具")

@mcp.tool()
def create_tar(source_path: str, output_path: str) -> str:
    """将文件或目录打包为tar.gz压缩包
    
    Args:
        source_path: 要压缩的文件或目录路径
        output_path: 输出的tar.gz文件路径
        
    Returns:
        操作结果信息
    """
    try:
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(source_path, arcname=os.path.basename(source_path))
        return f"成功创建压缩包: {output_path}"
    except Exception as e:
        return f"创建压缩包失败: {str(e)}"

@mcp.tool()
def extract_tar(tar_path: str, output_dir: str) -> str:
    """解压tar.gz压缩包到指定目录
    
    Args:
        tar_path: 要解压的tar.gz文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        with tarfile.open(tar_path) as tar:
            tar.extractall(output_dir)
        return f"成功解压到目录: {output_dir}"
    except Exception as e:
        return f"解压失败: {str(e)}"

@mcp.tool()
def rpm_unpack(rpm_path: str, output_dir: str) -> str:
    """解压RPM包到指定目录
    
    Args:
        rpm_path: RPM文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        cmd = f"rpm2cpio {rpm_path} | cpio -idm -D {output_dir}"
        subprocess.run(cmd, shell=True, check=True)
        return f"成功解压RPM包到: {output_dir}"
    except subprocess.CalledProcessError as e:
        return f"解压RPM包失败: {str(e)}"

if __name__ == "__main__":
    mcp.run()