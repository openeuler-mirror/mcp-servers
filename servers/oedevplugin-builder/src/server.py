#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import re
from mcp.server.fastmcp import FastMCP, Context

# 创建MCP服务器
mcp = FastMCP("oeDevPlugin Builder")

# RPM构建目录
RPMBUILD_DIR = Path.home() / "rpmbuild"

def get_version_from_spec(spec_file: Path) -> str:
    """从spec文件解析版本号"""
    with open(spec_file, 'r') as f:
        for line in f:
            if line.startswith('Version:'):
                return line.split(':')[1].strip()
    return ""

@mcp.tool()
def build_tar(ctx: Context, package_name: str) -> str:
    """将最新源码打包成tar.gz文件并放到~/rpmbuild/SOURCES目录
    
    Args:
        package_name: 要构建的软件包名
    """
    try:
        # 确保目录存在
        (RPMBUILD_DIR / "SOURCES").mkdir(parents=True, exist_ok=True)
        
        # 配置路径
        source_dir = Path.home() / f"openeuler_repos/openeuler/{package_name}"
        build_dir = Path.home() / f"openeuler_repos/src-openeuler/{package_name}"
        
        # 获取版本号(从spec文件读取)
        spec_file = build_dir / f"{package_name}.spec"
        if not spec_file.exists():
            return f"错误: 未找到spec文件 {spec_file}"
            
        version = get_version_from_spec(spec_file)
        if not version:
            return "错误: 无法从spec文件解析版本号"
        
        # 检查源码目录是否存在
        if not source_dir.exists():
            return "跳过打包: 未找到源码目录，继续RPM构建流程"
        
        # 打包最新源码为.gz格式
        tar_name = f"{package_name}-{version}.tar.gz"
        tar_path = RPMBUILD_DIR / "SOURCES" / tar_name
        
        # 删除已存在的压缩包
        if tar_path.exists():
            tar_path.unlink()
        
        # 直接创建.tar.gz文件
        shutil.make_archive(
            str(tar_path.with_suffix('').with_suffix('')),  # 移除.gz和.tar后缀
            'gztar',
            root_dir=source_dir
        )
        
        return f"成功创建最新tar包: {tar_path}"
    except Exception as e:
        return f"打包失败: {str(e)}"

@mcp.tool()
def build_rpm(ctx: Context, package_name: str) -> str:
    """使用spec文件构建最新RPM包
    
    Args:
        package_name: 要构建的软件包名
    """
    try:
        # 配置路径
        build_dir = Path.home() / f"openeuler_repos/src-openeuler/{package_name}"
        spec_file = build_dir / f"{package_name}.spec"
        
        # 确保spec文件存在
        if not spec_file.exists():
            return f"错误: 未找到spec文件 {spec_file}"
            
        # 从src-openeuler仓库拷贝所有文件到SOURCES目录
        sources_dir = RPMBUILD_DIR / "SOURCES"
        for item in build_dir.iterdir():
            if item.name != ".git":
                dest = sources_dir / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            
        # 执行rpmbuild命令
        cmd = [
            "rpmbuild",
            "-ba",
            "--define",
            f"_topdir {RPMBUILD_DIR}",
            str(spec_file)
        ]
        env = os.environ.copy()
        env["RPMBUILD"] = str(RPMBUILD_DIR)
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        
        # 查找生成的RPM包
        rpm_files = list((RPMBUILD_DIR / "RPMS").rglob("*.rpm"))
        if not rpm_files:
            return "构建完成但未找到RPM文件"
            
        return f"成功构建最新RPM包:\n{result.stdout}\n文件位置:\n" + "\n".join(str(f) for f in rpm_files)
    except subprocess.CalledProcessError as e:
        return f"RPM构建失败:\n{e.stderr}"
    except Exception as e:
        return f"构建过程中出错: {str(e)}"

if __name__ == "__main__":
    mcp.run()