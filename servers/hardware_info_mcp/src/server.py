from pydantic import Field
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
import subprocess
import json

mcp = FastMCP("hardwareInfoMcp")

class HardwareInfo:
    @staticmethod
    def _run_command(cmd: list) -> Dict[str, Any]:
        """执行命令并返回统一格式结果"""
        try:
            output = subprocess.check_output(
                cmd,
                stderr=subprocess.PIPE
            ).decode('utf-8')
            return {"status": "success", "data": output}
        except subprocess.CalledProcessError as e:
            return {"status": "error", "message": e.stderr.decode('utf-8').strip()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

@mcp.tool()
def get_hardware_info(
    sudo: bool = Field(default=True, description="是否需要sudo权限")
) -> Dict[str, Any]:
    """获取完整硬件信息
    
    示例用法:
    1. 获取完整硬件信息(需要sudo权限)
    2. 获取非特权模式下可访问的硬件信息(sudo=false)
    """
    try:
        cmd = ['lshw', '-json']
        if sudo:
            cmd.insert(0, 'sudo')
            
        lshw_output = HardwareInfo._run_command(cmd)
        if lshw_output['status'] != 'success':
            return lshw_output
            
        bios_cmd = ['dmidecode', '-t', 'bios']
        if sudo:
            bios_cmd.insert(0, 'sudo')
            
        bios_info = HardwareInfo._run_command(bios_cmd)
        
        return {
            "status": "success",
            "data": {
                "hardware": json.loads(lshw_output['data']),
                "bios": bios_info['data'] if bios_info['status'] == 'success' else None
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_cpu_info() -> Dict[str, Any]:
    """获取CPU信息
    
    示例用法:
    1. 获取CPU详细信息
    """
    return HardwareInfo._run_command(['lscpu'])

@mcp.tool()
def get_memory_info(human_readable: bool = Field(default=True, description="是否以人类可读格式显示")) -> Dict[str, Any]:
    """获取内存信息
    
    示例用法:
    1. 获取内存使用情况(人类可读格式)
    2. 获取原始内存数据(human_readable=false)
    """
    cmd = ['free']
    if human_readable:
        cmd.append('-h')
    return HardwareInfo._run_command(cmd)

if __name__ == "__main__":
    mcp.run()