import subprocess
import argparse
import os
import yaml
from pathlib import Path
from typing import Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vpn_manager_mcp")

global_config = {
    'VPN_CONFIG_DIR': os.path.expanduser('~/.config/vpn_manager/openvpn'),
    'IPSEC_CONFIG_DIR': os.path.expanduser('~/.config/vpn_manager/ipsec'),
    'GATEWAY_IP': None,
    'GATEWAY_PORT': None,
    'RECONNECT_ATTEMPTS': 3
}

def init_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--GATEWAY_IP', required=True)
    parser.add_argument('--GATEWAY_PORT', required=True)
    parser.add_argument('--VPN_CONFIG_DIR', required=False)
    parser.add_argument('--IPSEC_CONFIG_DIR', required=False)
    parser.add_argument('--RECONNECT_ATTEMPTS', required=False)
    
    args = parser.parse_args()
    
    global global_config
    if args.VPN_CONFIG_DIR:
        global_config['VPN_CONFIG_DIR'] = args.VPN_CONFIG_DIR
    if args.IPSEC_CONFIG_DIR:
        global_config['IPSEC_CONFIG_DIR'] = args.IPSEC_CONFIG_DIR
    if args.RECONNECT_ATTEMPTS:
        global_config['RECONNECT_ATTEMPTS'] = int(args.RECONNECT_ATTEMPTS)
    
    global_config['GATEWAY_IP'] = args.GATEWAY_IP
    global_config['GATEWAY_PORT'] = args.GATEWAY_PORT
    
    # 确保配置目录存在
    Path(global_config['VPN_CONFIG_DIR']).mkdir(parents=True, exist_ok=True)
    Path(f"{global_config['IPSEC_CONFIG_DIR']}/certs").mkdir(parents=True, exist_ok=True)
    Path(f"{global_config['IPSEC_CONFIG_DIR']}/private").mkdir(parents=True, exist_ok=True)

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
def list_vpns() -> str:
    """List available VPN configurations"""
    return run_command(f"ls {global_config['VPN_CONFIG_DIR']}")

@mcp.tool()
def start_vpn(
    config: str = Field(..., description="VPN configuration file name"),
    auth: Optional[str] = Field(None, description="Authentication file path")
) -> str:
    """Start a VPN connection"""
    cmd = f"openvpn --config {global_config['VPN_CONFIG_DIR']}/{config}"
    if auth:
        cmd += f" --auth-user-pass {auth}"
    return run_command(cmd)

@mcp.tool()
def stop_vpn() -> str:
    """Stop all VPN connections"""
    return run_command("pkill openvpn")

@mcp.tool()
def get_vpn_status() -> str:
    """Get current VPN connection status"""
    return run_command("ipsec status")

@mcp.tool()
def show_configs() -> str:
    """Show available VPN configurations"""
    return run_command(f"ls {global_config['IPSEC_CONFIG_DIR']}/../ipsec.conf {global_config['IPSEC_CONFIG_DIR']}")

@mcp.tool()
def add_certificate(
    cert_path: str = Field(..., description="Certificate file path"),
    cert_type: str = Field(..., description="Certificate type (ca/cert/key)")
) -> str:
    """Add VPN certificate"""
    dest = f"{global_config['IPSEC_CONFIG_DIR']}/{cert_type}s/"
    return run_command(f"cp {cert_path} {dest} && ipsec rereadcerts")
    
if __name__ == "__main__":
    try:
        init_config()
        mcp.run()
    except Exception as e:
        print(f"MCP server failed: {str(e)}")
        raise

