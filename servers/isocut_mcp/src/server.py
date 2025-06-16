import subprocess
import shlex
import json
import os
from typing import Dict, List
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ISO 裁剪工具")

@mcp.tool()
def get_path_config(iso_dir: str = "/root/ison", temp_dir: str = "/root/temp") -> dict:
    """获取ISO和临时文件目录配置"""
    return {
        "status": "success",
        "iso_dir": iso_dir,
        "temp_dir": temp_dir
    }

@mcp.tool()
def list_available_isos(iso_dir: str) -> dict:
    """列出可用的基础 ISO 文件"""
    try:
        # 检查 ISO 目录下的 ISO 文件
        result = subprocess.check_output(
            ['sudo', 'ls', iso_dir],
            text=True,
            stderr=subprocess.STDOUT
        )
        iso_files = [f for f in result.split('\n') if f.endswith('.iso')]
        return {"status": "success", "available_isos": iso_files}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def customize_iso(input_iso: str, output_name: str, iso_dir: str, temp_dir: str,
                 ks_config: str = "default.ks") -> dict:
    """
    裁剪 ISO 镜像
    :param input_iso: 输入 ISO 文件名
    :param output_name: 输出 ISO 文件名 (无需扩展名)
    :param ks_config: Kickstart 配置文件名
    :param iso_dir: ISO文件目录路径
    :param temp_dir: 临时文件目录路径
    """
    try:
        # 使用动态路径构建完整路径
        input_path = os.path.join(iso_dir, input_iso)
        ks_path = os.path.join(iso_dir, ks_config)
        output_path = os.path.join(iso_dir, f"{output_name}.iso")
        work_dir = os.path.join(temp_dir, output_name)
        
        # 创建临时目录
        os.makedirs(work_dir, exist_ok=True)
        
        # 执行 ISO 裁剪命令 (参考 isocut 语法)
        cmd = f"sudo isocut -t {work_dir} -k {ks_path} {input_path} {output_path}"
        result = subprocess.check_output(
            shlex.split(cmd),
            text=True,
            stderr=subprocess.STDOUT
        )
        
        # 清理临时目录
        subprocess.run(['sudo', 'rm', '-rf', work_dir])
        
        return {
            "status": "success",
            "output": result,
            "output_iso": output_path
        }
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e.output)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def generate_ks_config(packages: List[str], iso_dir: str,
                      config_name: str = "custom.ks") -> dict:
    """
    生成 Kickstart 配置文件
    :param packages: 需要包含的软件包列表
    :param config_name: 配置文件名
    :param iso_dir: ISO文件目录路径
    """
    try:
        config_path = os.path.join(iso_dir, config_name)
        
        # 基础 Kickstart 配置模板
        base_config = """
        # 基础系统配置
        lang en_US.UTF-8
        keyboard us
        timezone Asia/Shanghai
        rootpw --plaintext password
        reboot
        
        # 分区设置
        autopart --type=lvm
        
        # 软件包选择
        %packages
        @^minimal-environment
        """
        
        # 添加用户指定的软件包
        package_section = '\n'.join(packages)
        full_config = base_config + package_section + "\n%end"
        
        # 写入配置文件
        with open(config_path, 'w') as f:
            f.write(full_config)
        
        return {
            "status": "success",
            "config_path": config_path,
            "included_packages": packages
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()