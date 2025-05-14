from mcp.server.fastmcp import FastMCP
import os

LIBVIRT_IMAGE_DIR = "/var/lib/libvirt/images"
DEFAULT_IMAGE_NAME = "openEuler-24.03-LTS-SP1-`uname -m`.qcow2"
DEFAULT_IMAGE_URL = "https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP1/virtual_machine_img/`uname -m`/openEuler-24.03-LTS-SP1-`uname -m`.qcow2.xz"

# Initialize FastMCP server
mcp = FastMCP("虚拟机管理工具", log_level="ERROR")

@mcp.tool()
async def install_dependent_software() -> str:
    """安装virt-install和virsh等相关命令的依赖软件
    """
    return "请帮我执行: { " + f"""
sudo yum install -y qemu-kvm libvirt virt-install libvirt-client bridge-utils;
sudo systemctl start libvirtd;
sudo wget -P {LIBVIRT_IMAGE_DIR} {DEFAULT_IMAGE_URL};
sudo unxz -k {LIBVIRT_IMAGE_DIR}/{DEFAULT_IMAGE_NAME}.xz
""" + " }"

@mcp.tool()
async def create_vm(
    name: str,
    memory: int,
    vcpus: int,
    size: int,
    model_disk: str = f"{LIBVIRT_IMAGE_DIR}/{DEFAULT_IMAGE_NAME}"
) -> str:
    """用virt-install命令创建虚拟机

    Args:
        name: 虚拟机的名称
        memory: 给虚拟机分配的内存大小,单位MB
        vcpus: 给虚拟机分配的虚拟CPU数量
        size: 给虚拟机分配的磁盘大小,单位GB
        model_disk: 创建虚拟机所使用的模板镜像
    """
    return "请帮我执行: { " + f"""
sudo cp {model_disk} {LIBVIRT_IMAGE_DIR}/{name}.qcow2;
sudo virt-install --name {name} \
    --memory {memory} --vcpus {vcpus} \
    --disk /var/lib/libvirt/images/{name}.qcow2,size={size} \
    --import --os-variant openeuler22.03 \
    --network network=default --graphics none \
    --noautoconsole;
""" + " }"

@mcp.tool()
async def delete_vm(name: str) -> str:
    """删除指定的virsh虚拟机

    Args:
        name: 虚拟机的名称
    """
    return "请帮我执行: { " + f"""
sudo virsh destroy {name};
sudo virsh undefine {name};
sudo rm -f {LIBVIRT_IMAGE_DIR}/{name}.qcow2;
""" + " }"

@mcp.tool()
async def get_vm_ip(name: str) -> str:
    """获取所有virsh虚拟机的IP

    Args:
        name: 虚拟机的名称
    """
    return "请帮我执行: { " + f"""
sudo virsh domifaddr {name}; 
""" + " }"

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
