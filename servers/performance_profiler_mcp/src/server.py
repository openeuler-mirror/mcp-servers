#!/usr/bin/env python3
from pydantic import Field
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import tempfile
import os
import argparse
from pathlib import Path
import yaml

# 创建MCP实例
mcp = FastMCP("performance_profiler_mcp")

# 全局配置
global_config = {
    'HOME_DIR': None,
    'PERF_PATH': '/usr/bin/perf',
    'VALGRIND_PATH': '/usr/bin/valgrind'
}

@mcp.tool()
def perf_profile(
    program: str = Field(..., description="要剖析的程序路径"),
    duration: int = Field(default=10, description="剖析持续时间(秒)")
) -> Dict[str, Any]:
    """使用perf进行性能分析"""
    try:
        # 创建临时文件保存perf报告
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.perf') as tmp:
            cmd = [
                global_config['PERF_PATH'], 'record',
                '-o', tmp.name,
                '--', program
            ]
            # 运行perf record指定时间
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.wait(timeout=duration)
            process.terminate()
            
            # 生成分析报告
            report_cmd = [global_config['PERF_PATH'], 'report', '-i', tmp.name]
            report = subprocess.check_output(
                report_cmd,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            return {
                "status": "success",
                "report": report
            }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def valgrind_profile(
    program: str = Field(..., description="要分析的程序路径"),
    args: Optional[str] = Field(default=None, description="程序参数")
) -> Dict[str, Any]:
    """使用valgrind进行内存分析"""
    try:
        cmd = [global_config['VALGRIND_PATH'], '--leak-check=full', program]
        if args:
            cmd.extend(args.split())
            
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        return {
            "status": "success",
            "report": output
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "report": e.output
        }
    except Exception as e:
        return {"error": str(e)}

def init_config():
    """初始化配置"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--HOME_DIR', required=True)
    parser.add_argument('--PERF_PATH', default='/usr/bin/perf')
    parser.add_argument('--VALGRIND_PATH', default='/usr/bin/valgrind')
    
    args = parser.parse_args()

    global global_config
    global_config.update({
        'HOME_DIR': args.HOME_DIR,
        'PERF_PATH': args.PERF_PATH,
        'VALGRIND_PATH': args.VALGRIND_PATH
    })

    # 确保配置目录存在
    config_dir = os.path.expanduser('~/.config/performance_profiler')
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    
    # 写入配置文件
    config_file = os.path.join(config_dir, 'config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(global_config, f, default_flow_style=False)

if __name__ == "__main__":
    init_config()
    mcp.run()