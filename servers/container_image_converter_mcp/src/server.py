import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("容器镜像转换工具")

def convert_image(source: str, destination: str, src_format: str = None, dest_format: str = None):
    """使用skopeo转换镜像格式"""
    cmd = ['skopeo', 'copy']
    if src_format:
        cmd.extend(['--src-format', src_format])
    if dest_format:
        cmd.extend(['--dest-format', dest_format])
    cmd.extend([source, destination])
    
    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        )
        return {"status": "success", "message": "Image converted successfully"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": str(e), "output": e.stderr}

def push_image(image: str, registry: str, tag: str, authfile: str = None):
    """使用buildah推送镜像到仓库"""
    cmd = ['buildah', 'push']
    if authfile:
        cmd.extend(['--authfile', authfile])
    cmd.extend([image, f"{registry}:{tag}"])
    
    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        )
        return {"status": "success", "message": "Image pushed successfully"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": str(e), "output": e.stderr}

@mcp.tool()
def convert_image_format(
    source: str,
    destination: str,
    src_format: str = None,
    dest_format: str = None
) -> dict:
    """
    转换容器镜像格式
    :param source: 源镜像地址
    :param destination: 目标镜像地址
    :param src_format: 源镜像格式(可选)
    :param dest_format: 目标镜像格式(可选)
    :return: 转换结果(JSON格式)
    """
    return convert_image(source, destination, src_format, dest_format)

@mcp.tool()
def push_image_to_registry(
    image: str,
    registry: str,
    tag: str,
    authfile: str = None
) -> dict:
    """
    推送镜像到仓库
    :param image: 本地镜像名称
    :param registry: 目标仓库地址
    :param tag: 镜像标签
    :param authfile: 认证文件路径(可选)
    :return: 推送结果(JSON格式)
    """
    return push_image(image, registry, tag, authfile)

if __name__ == "__main__":
    mcp.run()