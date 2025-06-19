import os
import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("跨发行版打包工具")

def build_with_fpm(source_dir, package_name, version, output_format="rpm"):
    """
    使用fpm工具构建软件包
    :param source_dir: 源代码目录
    :param package_name: 包名
    :param version: 版本号
    :param output_format: 输出格式(rpm/deb等)
    :return: 构建结果
    """
    try:
        # 检查是否需要sudo权限
        need_sudo = False
        if any(path.startswith(('/usr', '/etc', '/var', '/opt'))
               for path in [source_dir] +
               [os.path.join(source_dir, f) for f in os.listdir(source_dir)]):
            need_sudo = True
            
        cmd = ['fpm', '-s', 'dir', '-t', output_format,
              '-n', package_name, '-v', version,
              '-C', source_dir]
              
        if need_sudo:
            cmd = ['sudo'] + cmd
            
        result = subprocess.run(
            cmd,
            check=True, capture_output=True, text=True
        )
        return {
            "status": "success",
            "output": result.stdout,
            "package": f"{package_name}-{version}.{output_format}"
        }
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": str(e), "output": e.stderr}

def build_with_checkinstall(source_dir, package_name, version):
    """
    使用checkinstall构建安装包
    :param source_dir: 源代码目录
    :param package_name: 包名
    :param version: 版本号
    :return: 构建结果
    """
    try:
        os.chdir(source_dir)
        result = subprocess.run(
            ['checkinstall', '--pkgname', package_name, 
             '--pkgversion', version, '--default'],
            check=True, capture_output=True, text=True
        )
        return {
            "status": "success",
            "output": result.stdout,
            "package": f"{package_name}-{version}.rpm"
        }
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": str(e), "output": e.stderr}

@mcp.tool()
def build_rpm_package(source_dir: str, package_name: str, version: str) -> dict:
    """
    构建RPM包
    :param source_dir: 源代码目录路径
    :param package_name: 包名
    :param version: 版本号
    :return: 构建结果(JSON格式)
    """
    return build_with_fpm(source_dir, package_name, version, "rpm")

@mcp.tool()
def build_deb_package(source_dir: str, package_name: str, version: str) -> dict:
    """
    构建DEB包
    :param source_dir: 源代码目录路径
    :param package_name: 包名
    :param version: 版本号
    :return: 构建结果(JSON格式)
    """
    return build_with_fpm(source_dir, package_name, version, "deb")

@mcp.tool()
def build_with_checkinstall_tool(source_dir: str, package_name: str, version: str) -> dict:
    """
    使用checkinstall构建安装包
    :param source_dir: 源代码目录路径
    :param package_name: 包名
    :param version: 版本号
    :return: 构建结果(JSON格式)
    """
    return build_with_checkinstall(source_dir, package_name, version)

if __name__ == "__main__":
    mcp.run()