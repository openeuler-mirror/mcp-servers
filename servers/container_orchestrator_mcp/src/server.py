from pydantic import Field
from typing import Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import os
import argparse
from pathlib import Path

mcp = FastMCP("containerOrchestrator")

global_config = {
    'DEFAULT_COMPOSE_FILE': 'docker-compose.yml',
    'DOCKER_COMPOSE_PATH': '/usr/local/bin/docker-compose'
}

def _run_command(cmd: list, compose_file: Optional[str] = None) -> dict:
    """执行命令并返回统一格式结果"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "success": True,
            "output": result.stdout,
            "error": result.stderr
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "output": e.stdout,
            "error": e.stderr
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }

@mcp.tool()
def compose_up(
    compose_file: Optional[str] = Field(
        default=None,
        description="docker-compose文件路径，默认为当前目录下的docker-compose.yml"
    )
) -> dict:
    """启动docker-compose服务
    
    示例用法:
    1. 启动默认的docker-compose.yml文件
    2. 启动指定路径的compose文件: /path/to/docker-compose.yml

    命令示例:
    1. docker-compose -f docker-compose.yml up -d
    2. docker-compose -f /path/to/compose.yml up -d
    """
    file = compose_file if compose_file else global_config['DEFAULT_COMPOSE_FILE']
    cmd = [
        global_config['DOCKER_COMPOSE_PATH'],
        '-f', file,
        'up', '-d'
    ]
    return _run_command(cmd, compose_file)

@mcp.tool()
def compose_down(
    compose_file: Optional[str] = Field(
        default=None,
        description="docker-compose文件路径，默认为当前目录下的docker-compose.yml"
    )
) -> dict:
    """停止并移除docker-compose服务
    
    示例用法:
    1. 停止默认的docker-compose.yml文件定义的服务
    2. 停止指定路径的compose文件定义的服务: /path/to/docker-compose.yml

    命令示例:
    1. docker-compose -f docker-compose.yml down
    2. docker-compose -f /path/to/compose.yml down
    """
    file = compose_file if compose_file else global_config['DEFAULT_COMPOSE_FILE']
    cmd = [
        global_config['DOCKER_COMPOSE_PATH'],
        '-f', file,
        'down'
    ]
    return _run_command(cmd, compose_file)

def init_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--DEFAULT_COMPOSE_FILE', default='docker-compose.yml')
    parser.add_argument('--DOCKER_COMPOSE_PATH', default='/usr/local/bin/docker-compose')
    
    args = parser.parse_args()

    global global_config
    global_config.update({
        'DEFAULT_COMPOSE_FILE': args.DEFAULT_COMPOSE_FILE,
        'DOCKER_COMPOSE_PATH': args.DOCKER_COMPOSE_PATH
    })

if __name__ == "__main__":
    init_config()
    mcp.run()