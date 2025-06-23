import subprocess
import json
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Anaconda核心命令管理服务")

@mcp.tool()
def conda_activate(env_name: str) -> dict:
    """激活conda环境"""
    try:
        subprocess.check_output(['conda', 'activate', env_name],
                             text=True,
                             stderr=subprocess.STDOUT)
        return {"status": "success", "env_name": env_name}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def conda_deactivate() -> dict:
    """退出当前conda环境"""
    try:
        subprocess.check_output(['conda', 'deactivate'],
                             text=True,
                             stderr=subprocess.STDOUT)
        return {"status": "success"}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def conda_install(package_name: str, env_name: str = None) -> dict:
    """安装conda包"""
    cmd = ['conda', 'install', '-y', package_name]
    if env_name:
        cmd.extend(['-n', env_name])
    
    try:
        subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {"status": "success", "package": package_name}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def conda_list(env_name: str = None) -> dict:
    """列出已安装的包"""
    cmd = ['conda', 'list']
    if env_name:
        cmd.extend(['-n', env_name])
    
    try:
        result = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {"packages": result.splitlines()}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def conda_create(env_name: str, python_version: str = None) -> dict:
    """创建新的conda环境"""
    cmd = ['conda', 'create', '-n', env_name, '-y']
    if python_version:
        cmd.extend(['python=' + python_version])
    
    try:
        subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {"status": "success", "env_name": env_name}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def conda_env_list() -> dict:
    """列出所有conda环境"""
    try:
        result = subprocess.check_output(['conda', 'env', 'list'],
                                       text=True,
                                       stderr=subprocess.STDOUT)
        return {"environments": result.splitlines()}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def conda_update(package_name: str = None, env_name: str = None) -> dict:
    """更新conda包"""
    cmd = ['conda', 'update', '-y']
    if package_name:
        cmd.append(package_name)
    if env_name:
        cmd.extend(['-n', env_name])
    
    try:
        subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {"status": "success"}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    mcp.run()