import os
import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("CMake构建工具")

def run_cmd(cmd: list, cwd: str = None) -> dict:
    """执行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

@mcp.tool()
def configure(project_path: str, build_type: str = "Debug", build_dir: str = "build") -> dict:
    """
    配置CMake项目
    :param project_path: 项目根目录路径(包含CMakeLists.txt)
    :param build_type: 构建类型(Debug|Release|RelWithDebInfo|MinSizeRel)
    :param build_dir: 构建目录名称(相对于项目路径)
    :return: 执行结果字典
    """
    full_build_dir = os.path.join(project_path, build_dir)
    os.makedirs(full_build_dir, exist_ok=True)
    
    cmake_cmd = [
        "cmake", 
        f"-DCMAKE_BUILD_TYPE={build_type}", 
        ".."
    ]
    return run_cmd(cmake_cmd, full_build_dir)

@mcp.tool() 
def build(project_path: str, build_dir: str = "build", target: str = None, parallel: int = None) -> dict:
    """
    构建CMake项目
    :param project_path: 项目根目录路径
    :param build_dir: 构建目录名称
    :param target: 指定构建目标(可选)
    :param parallel: 并行构建线程数(可选)
    :return: 执行结果字典
    """
    full_build_dir = os.path.join(project_path, build_dir)
    build_cmd = ["cmake", "--build", "."]
    
    if target:
        build_cmd.extend(["--target", target])
    if parallel:
        build_cmd.extend(["--parallel", str(parallel)])
    
    return run_cmd(build_cmd, full_build_dir)

@mcp.tool()
def install(project_path: str, build_dir: str = "build", prefix: str = None) -> dict:
    """
    安装构建目标
    :param project_path: 项目根目录路径
    :param build_dir: 构建目录名称
    :param prefix: 安装前缀路径(可选)
    :return: 执行结果字典
    """
    full_build_dir = os.path.join(project_path, build_dir)
    install_cmd = ["cmake", "--install", "."]
    
    if prefix:
        install_cmd.extend(["--prefix", prefix])
    
    return run_cmd(install_cmd, full_build_dir)

@mcp.tool()
def clean(project_path: str, build_dir: str = "build") -> dict:
    """
    清理构建目录
    :param project_path: 项目根目录路径
    :param build_dir: 构建目录名称
    :return: 执行结果字典
    """
    full_build_dir = os.path.join(project_path, build_dir)
    if os.path.exists(full_build_dir):
        return run_cmd(["cmake", "--build", ".", "--target", "clean"], full_build_dir)
    return {"status": "skipped", "message": f"构建目录 {build_dir} 不存在"}

if __name__ == "__main__":
    mcp.run()