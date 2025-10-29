import os
import subprocess
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("EFI Boot Manager")

@mcp.tool()
def list_efi_entries() -> str:
    """列出所有EFI启动项
    
    Returns:
        EFI启动项列表信息
    """
    try:
        result = subprocess.run(
            ["efibootmgr"],
            check=True,
            capture_output=True,
            text=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"获取EFI启动项失败: {e.stderr or str(e)}"
    except FileNotFoundError:
        return "错误: efibootmgr 工具未安装"

@mcp.tool()
def create_efi_entry(
    label: str,
    disk: str,
    partition: str,
    efi_path: str = "\\EFI\\BOOT\\bootx64.efi"
) -> str:
    """创建新的EFI启动项
    
    Args:
        label: 启动项显示名称
        disk: 磁盘设备 (如: /dev/sda)
        partition: 分区号 (如: 1)
        efi_path: EFI文件路径 (默认: \\EFI\\BOOT\\bootx64.efi)
        
    Returns:
        操作结果信息
    """
    try:
        cmd = [
            "efibootmgr",
            "--create",
            "--disk", disk,
            "--part", partition,
            "--label", label,
            "--loader", efi_path
        ]
        
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        
        return f"成功创建EFI启动项: {label}\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"创建EFI启动项失败: {e.stderr or str(e)}"

@mcp.tool()
def delete_efi_entry(bootnum: str) -> str:
    """删除指定的EFI启动项
    
    Args:
        bootnum: 启动项编号 (如: Boot0001)
        
    Returns:
        操作结果信息
    """
    try:
        result = subprocess.run(
            ["efibootmgr", "--bootnum", bootnum, "--delete-bootnum"],
            check=True,
            capture_output=True,
            text=True
        )
        
        return f"成功删除EFI启动项: {bootnum}\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"删除EFI启动项失败: {e.stderr or str(e)}"

@mcp.tool()
def set_boot_order(boot_order: str) -> str:
    """设置EFI启动顺序
    
    Args:
        boot_order: 启动顺序 (如: 0001,0002,0003)
        
    Returns:
        操作结果信息
    """
    try:
        result = subprocess.run(
            ["efibootmgr", "--bootorder", boot_order],
            check=True,
            capture_output=True,
            text=True
        )
        
        return f"成功设置启动顺序: {boot_order}\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"设置启动顺序失败: {e.stderr or str(e)}"

@mcp.tool()
def set_next_boot(bootnum: str) -> str:
    """设置下一次启动的EFI项
    
    Args:
        bootnum: 启动项编号 (如: Boot0001)
        
    Returns:
        操作结果信息
    """
    try:
        result = subprocess.run(
            ["efibootmgr", "--bootnext", bootnum],
            check=True,
            capture_output=True,
            text=True
        )
        
        return f"成功设置下次启动项: {bootnum}\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"设置下次启动项失败: {e.stderr or str(e)}"

@mcp.tool()
def get_efi_variables() -> str:
    """获取EFI变量信息
    
    Returns:
        EFI变量信息
    """
    try:
        result = subprocess.run(
            ["efibootmgr", "--verbose"],
            check=True,
            capture_output=True,
            text=True
        )
        
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"获取EFI变量失败: {e.stderr or str(e)}"

if __name__ == "__main__":
    mcp.run()