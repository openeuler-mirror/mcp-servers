import os
import subprocess
import json
import logging
from pathlib import Path
from typing import Optional, TypedDict
from mcp.server.fastmcp import FastMCP

# 初始化日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 子进程调用通用参数
SUBPROCESS_KWARGS = {
    'check': True,
    'capture_output': True,
    'text': True,
    'encoding': 'utf-8'
}

class ConversionResult(TypedDict, total=False):
    status: str
    output: str
    rpm_file: str
    error: str

mcp = FastMCP("deb转rpm工具")

def check_dependencies() -> bool:
    """检查是否安装了alien和rpm-build
    
    Returns:
        bool: 如果所有依赖都安装返回True，否则返回False
    """
    tools = ['alien', 'rpmbuild']
    missing = []
    
    for tool in tools:
        try:
            subprocess.run([tool, '--version'], **SUBPROCESS_KWARGS)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"依赖检查失败: {tool} 未安装")
            missing.append(tool)
    
    if missing:
        logger.error(f"缺少必要依赖: {', '.join(missing)}")
        return False
    return True

def convert_deb_to_rpm(deb_path: str, output_dir: Optional[str] = None) -> ConversionResult:
    """将deb包转换为rpm包
    
    Args:
        deb_path: deb包路径
        output_dir: 输出目录(可选)
        
    Returns:
        ConversionResult: 包含转换结果或错误信息的字典
    """
    deb_path_obj = Path(deb_path)
    if not deb_path_obj.exists():
        error_msg = f"文件 {deb_path} 不存在"
        logger.error(error_msg)
        return {"error": error_msg}
    
    if not check_dependencies():
        error_msg = "缺少依赖: 请先安装alien和rpm-build"
        logger.error(error_msg)
        return {"error": error_msg}

    try:
        cmd = ['alien', '-r', str(deb_path_obj)]
        if output_dir:
            output_dir_obj = Path(output_dir)
            output_dir_obj.mkdir(parents=True, exist_ok=True)
            cmd.extend(['--output-dir', str(output_dir_obj)])
        
        logger.info(f"开始转换: {deb_path}")
        result = subprocess.run(cmd, **SUBPROCESS_KWARGS)
        
        rpm_file = deb_path_obj.with_suffix('.rpm')
        if output_dir:
            rpm_file = output_dir_obj / rpm_file.name
        
        logger.info(f"转换成功: 生成RPM文件 {rpm_file}")
        return {
            "status": "success",
            "output": result.stdout,
            "rpm_file": str(rpm_file)
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"转换失败: {e.stderr}")
        return {
            "error": str(e),
            "output": e.stderr
        }
    except Exception as e:
        logger.error(f"转换过程中发生意外错误: {str(e)}")
        return {
            "error": f"内部错误: {str(e)}"
        }

@mcp.tool()
def deb_to_rpm(deb_path: str, output_dir: Optional[str] = None) -> ConversionResult:
    """将deb包转换为rpm包
    
    Args:
        deb_path: deb包路径
        output_dir: 输出目录(可选)
        
    Returns:
        dict: 转换结果(JSON格式)
    """
    return convert_deb_to_rpm(deb_path, output_dir)

if __name__ == "__main__":
    mcp.run()