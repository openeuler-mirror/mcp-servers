from pydantic import Field
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
import subprocess
import json

mcp = FastMCP("lvmManager")

class LVMManager:
    @staticmethod
    def list_volume_groups() -> Dict[str, Any]:
        """List all volume groups"""
        try:
            result = subprocess.run(['vgs', '--reportformat=json'], 
                                  capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            return {"error": str(e), "stderr": e.stderr}

    @staticmethod
    def list_logical_volumes() -> Dict[str, Any]:
        """List all logical volumes"""
        try:
            result = subprocess.run(['lvs', '--reportformat=json'],
                                  capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            return {"error": str(e), "stderr": e.stderr}

    @staticmethod
    def list_physical_volumes() -> Dict[str, Any]:
        """List all physical volumes"""
        try:
            result = subprocess.run(['pvs', '--reportformat=json'],
                                  capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            return {"error": str(e), "stderr": e.stderr}

    @staticmethod
    def get_lvm_info() -> Dict[str, Any]:
        """Get comprehensive LVM information"""
        return {
            "volume_groups": LVMManager.list_volume_groups(),
            "logical_volumes": LVMManager.list_logical_volumes(),
            "physical_volumes": LVMManager.list_physical_volumes()
        }

@mcp.tool()
def list_volume_groups() -> Dict[str, Any]:
    """List all volume groups
    
    Example usage:
    1. List all volume groups on the system
    """
    return LVMManager.list_volume_groups()

@mcp.tool()
def list_logical_volumes() -> Dict[str, Any]:
    """List all logical volumes
    
    Example usage:
    1. List all logical volumes on the system
    """
    return LVMManager.list_logical_volumes()

@mcp.tool()
def list_physical_volumes() -> Dict[str, Any]:
    """List all physical volumes
    
    Example usage:
    1. List all physical volumes on the system
    """
    return LVMManager.list_physical_volumes()

@mcp.tool()
def get_lvm_info() -> Dict[str, Any]:
    """Get comprehensive LVM information
    
    Example usage:
    1. Get complete LVM information including VGs, LVs and PVs
    """
    return LVMManager.get_lvm_info()

if __name__ == "__main__":
    mcp.run()