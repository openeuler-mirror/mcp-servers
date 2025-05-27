from pydantic import Field
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import subprocess

mcp = FastMCP("pciInfoMcp")

@mcp.tool()
def get_pci_info(
    verbose: bool = Field(default=True, description="是否显示详细信息")
) -> Dict[str, Any]:
    """获取PCI设备详细信息
    
    示例用法:
    1. 获取所有PCI设备的详细信息
    2. 获取PCI设备的简要信息(verbose=false)
    
    命令:
    1. 详细模式: lspci -v -mm
    2. 简要模式: lspci
    """
    try:
        cmd = ["lspci", "-mm"]
        if verbose:
            cmd.append("-v")
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "data": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def list_pci_devices(
    filter: Optional[str] = Field(default=None, description="过滤设备类型，如VGA、Network等")
) -> Dict[str, Any]:
    """列出所有PCI设备
    
    示例用法:
    1. 列出所有PCI设备
    2. 只列出VGA设备
    
    命令:
    1. 基本命令: lspci
    2. 过滤命令: lspci | grep [filter]
    """
    try:
        cmd = ["lspci"]
        if filter:
            cmd.extend(["|", "grep", filter])
            
        result = subprocess.run(
            " ".join(cmd),
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "data": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()