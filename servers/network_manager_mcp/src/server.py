import subprocess
from typing import Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("network_manager_mcp")

def run_command(cmd: str) -> str:
    try:
        result = subprocess.run(
            cmd, 
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"

@mcp.tool()
def list_interfaces() -> str:
    """List all network interfaces"""
    return run_command("ip -o link show")

@mcp.tool()
def get_interface_status(
    interface: str = Field(..., description="Network interface name")
) -> str:
    """Get status of a specific network interface"""
    return run_command(f"ip addr show {interface}")

@mcp.tool()
def configure_ip_address(
    interface: str = Field(..., description="Network interface name"),
    ip_address: str = Field(..., description="IP address with CIDR notation (e.g. 192.168.1.1/24)"),
    gateway: Optional[str] = Field(None, description="Default gateway IP address")
) -> str:
    """Configure IP address on a network interface"""
    cmd = f"nmcli con mod {interface} ipv4.addresses {ip_address}"
    if gateway:
        cmd += f" ipv4.gateway {gateway}"
    cmd += " && nmcli con up {interface}"
    return run_command(cmd)

@mcp.tool()
def show_connections() -> str:
    """Show all NetworkManager connections"""
    return run_command("nmcli con show")

@mcp.tool()
def toggle_interface(
    interface: str = Field(..., description="Network interface name"),
    state: str = Field("up", description="Interface state (up/down)")
) -> str:
    """Bring interface up or down"""
    return run_command(f"ip link set {interface} {state}")

if __name__ == "__main__":
    mcp.run()  

