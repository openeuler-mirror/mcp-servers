from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("KVM虚拟机管理工具", log_level="INFO")

@mcp.tool()
async def create_vm(name: str, memory: int, vcpus: int, disk_size: int) -> str:
    """创建KVM虚拟机
    
    Args:
        name: 虚拟机名称
        memory: 内存大小(MB)
        vcpus: CPU核心数
        disk_size: 磁盘大小(GB)
    """
    return "请帮我执行: { " + f"""
sudo virt-install --name {name} \\
    --memory {memory} --vcpus {vcpus} \\
    --disk size={disk_size} \\
    --cdrom /dev/null --os-variant generic \\
    --network network=default --graphics none \\
    --noautoconsole
""" + " }"

@mcp.tool()
async def delete_vm(name: str) -> str:
    """删除KVM虚拟机
    
    Args:
        name: 虚拟机名称
    """
    return "请帮我执行: { " + f"""
sudo virsh destroy {name};
sudo virsh undefine {name};
""" + " }"

@mcp.tool()
async def start_vm(name: str) -> str:
    """启动KVM虚拟机
    
    Args:
        name: 虚拟机名称
    """
    return "请帮我执行: { " + f"""
sudo virsh start {name}
""" + " }"

@mcp.tool()
async def stop_vm(name: str) -> str:
    """停止KVM虚拟机
    
    Args:
        name: 虚拟机名称
    """
    return "请帮我执行: { " + f"""
sudo virsh shutdown {name}
""" + " }"

@mcp.tool()
async def list_vms() -> str:
    """列出所有KVM虚拟机"""
    return "请帮我执行: { " + """
sudo virsh list --all
""" + " }"

@mcp.tool()
async def get_vm_status(name: str) -> str:
    """获取虚拟机状态
    
    Args:
        name: 虚拟机名称
    """
    return "请帮我执行: { " + f"""
sudo virsh dominfo {name}
""" + " }"

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')