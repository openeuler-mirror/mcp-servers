from pydantic import Field
from typing import Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import json
from pathlib import Path

mcp = FastMCP("sshManager")

@mcp.tool()
def ssh_connect(
    host: str = Field(..., description="SSH server hostname or IP"),
    username: str = Field(..., description="SSH username"),
    port: int = Field(default=22, description="SSH port number"),
    key_path: Optional[str] = Field(default=None, description="Path to SSH private key")
) -> dict:
    """Establish SSH connection
    
    Example usage:
    1. Connect to example.com with user root
    2. Connect to 192.168.1.1 with user admin using key ~/.ssh/id_rsa
    3. Connect to test.example.com on port 2222 with user test
    """
    cmd = ['ssh']
    if key_path:
        cmd.extend(['-i', str(key_path)])
    cmd.extend(['-p', str(port), f'{username}@{host}'])
    try:
        subprocess.run(cmd, check=True)
        return {'status': 'success'}
    except subprocess.CalledProcessError as e:
        return {'status': 'error', 'message': str(e)}

@mcp.tool()
def scp_transfer(
    source: str = Field(..., description="Source file path"),
    destination: str = Field(..., description="Destination file path"),
    recursive: bool = Field(default=False, description="Recursive copy for directories")
) -> dict:
    """Transfer files using SCP
    
    Example usage:
    1. Copy local.txt to remote:/tmp/remote.txt
    2. Recursively copy /local/dir to remote:/tmp/dir
    """
    cmd = ['scp']
    if recursive:
        cmd.append('-r')
    cmd.extend([source, destination])
    try:
        subprocess.run(cmd, check=True)
        return {'status': 'success'}
    except subprocess.CalledProcessError as e:
        return {'status': 'error', 'message': str(e)}

if __name__ == '__main__':
    mcp.run()