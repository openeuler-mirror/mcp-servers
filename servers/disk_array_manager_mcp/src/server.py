import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("磁盘阵列管理工具")

def run_mdadm_command(args: list) -> str:
    """执行mdadm命令并返回结果"""
    try:
        result = subprocess.check_output(
            ['sudo', 'mdadm'] + args,
            stderr=subprocess.STDOUT,
            text=True
        )
        return result or "操作成功"
    except subprocess.CalledProcessError as e:
        return f"操作失败: {e.output}"

@mcp.tool()
def create_raid(device: str, level: str, *disks: str) -> str:
    """创建RAID阵列
    
    Args:
        device: RAID设备路径(如/dev/md0)
        level: RAID级别(如raid1, raid5等)
        disks: 要加入RAID的磁盘列表
    """
    return run_mdadm_command([
        '--create', device,
        '--level=' + level,
        '--raid-devices=' + str(len(disks))
    ] + list(disks))

@mcp.tool() 
def remove_raid(device: str) -> str:
    """删除RAID阵列"""
    return run_mdadm_command(['--stop', device])

@mcp.tool()
def raid_status(device: str) -> str:
    """查询RAID状态"""
    return run_mdadm_command(['--detail', device])

@mcp.tool()
def add_disk(raid_device: str, disk: str) -> str:
    """添加磁盘到RAID阵列"""
    return run_mdadm_command(['--add', raid_device, disk])

@mcp.tool()
def remove_disk(raid_device: str, disk: str) -> str:
    """从RAID阵列移除磁盘"""
    return run_mdadm_command(['--remove', raid_device, disk])

if __name__ == "__main__":
    mcp.run()