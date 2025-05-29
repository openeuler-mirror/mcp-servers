import os
import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("构建系统助手")

def run_cmake(project_path, build_type="Debug", build_dir="build"):
    """执行CMake配置"""
    full_build_dir = os.path.join(project_path, build_dir)
    os.makedirs(full_build_dir, exist_ok=True)
    
    try:
        result = subprocess.run(
            ["cmake", f"-DCMAKE_BUILD_TYPE={build_type}", ".."],
            cwd=full_build_dir,
            check=True,
            capture_output=True,
            text=True
        )
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stderr}

def run_make(project_path, build_dir="build", target=None):
    """执行Make构建"""
    full_build_dir = os.path.join(project_path, build_dir)
    
    make_cmd = ["make"]
    if target:
        make_cmd.append(target)
    
    try:
        result = subprocess.run(
            make_cmd,
            cwd=full_build_dir,
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
    :param project_path: 项目路径
    :param build_type: 构建类型(Debug|Release)
    :param build_dir: 构建目录名
    :return: 配置结果
    """
    if not os.path.exists(project_path):
        return {"error": f"项目路径 {project_path} 不存在"}
    
    return run_cmake(project_path, build_type, build_dir)

@mcp.tool()
def build(project_path: str, build_dir: str = "build", target: str = None) -> dict:
    """
    构建项目
    :param project_path: 项目路径
    :param build_dir: 构建目录名
    :param target: 构建目标(可选)
    :return: 构建结果
    """
    if not os.path.exists(project_path):
        return {"error": f"项目路径 {project_path} 不存在"}
    
    return run_make(project_path, build_dir, target)

if __name__ == "__main__":
    mcp.run()