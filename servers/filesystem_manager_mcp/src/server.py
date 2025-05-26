import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("文件系统管理工具")

@mcp.tool()
def create_filesystem(device: str, fstype: str = "ext4") -> str:
    """创建文件系统
    Args:
        device: 设备路径(如/dev/sdb1)
        fstype: 文件系统类型(ext4/xfs)
    """
    try:
        cmd = ["mkfs", "-t", fstype, device]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return f"成功在{device}上创建{fstype}文件系统"
    except subprocess.CalledProcessError as e:
        return f"创建文件系统失败: {e.stderr}"

@mcp.tool() 
def mount_filesystem(device: str, mountpoint: str, fstype: str = "auto") -> str:
    """挂载文件系统
    Args:
        device: 设备路径
        mountpoint: 挂载点目录
        fstype: 文件系统类型
    """
    try:
        cmd = ["mount", "-t", fstype, device, mountpoint]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return f"成功将{device}挂载到{mountpoint}"
    except subprocess.CalledProcessError as e:
        return f"挂载失败: {e.stderr}"

@mcp.tool()
def list_filesystems() -> str:
    """列出已挂载的文件系统"""
    try:
        result = subprocess.run(["mount"], check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"获取文件系统列表失败: {e.stderr}"

if __name__ == "__main__":
    mcp.run()