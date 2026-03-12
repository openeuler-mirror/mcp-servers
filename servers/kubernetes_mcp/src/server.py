from typing import Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import os
from pathlib import Path

mcp = FastMCP("k8sClusterManager")

global_config = {
    'KUBECTL_PATH': '/usr/bin/kubectl',
    'K3SCTL_PATH': '/usr/local/bin/k3s',
    'DEFAULT_CONTEXT': None
}

def _run_command(cmd: list) -> dict:
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
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }

@mcp.tool()
def cluster_status(cluster_type: str = "k8s") -> dict:
    """获取集群状态信息
    Args:
        cluster_type: 集群类型，可选值为 "k8s" 或 "k3s" 
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    if cluster_type == "k8s":
        cmd = [global_config['KUBECTL_PATH'], "cluster-info"]
    elif cluster_type == "k3s":
        cmd = [global_config['K3SCTL_PATH'], "status"]
    else:
        return {
            "success": False,
            "output": "",
            "error": "不支持的集群类型"
        }
    return _run_command(cmd)

@mcp.tool()
def get_nodes() -> dict:
    """获取集群节点信息
    Args:
        无 
    Returns:
        dict: 包含执行结果的字典，成功时包含data字段，包含节点信息的JSON数据
    """
    cmd = [global_config['KUBECTL_PATH'], "get", "nodes", "-o", "json"]
    result = _run_command(cmd)
    if result["success"]:
        try:
            result["data"] = json.loads(result["output"])
        except json.JSONDecodeError:
            pass
    return result

@mcp.tool()
def get_pods(namespace: Optional[str] = None) -> dict:
    """获取集群中的Pod信息
    Args:
        namespace: 命名空间
    Returns:
        dict: 包含执行结果的字典，成功时包含data字段，包含Pod信息的JSON数据
    """
    cmd = [global_config['KUBECTL_PATH'], "get", "pods", "-o", "json"]
    if namespace:
        cmd.extend(["-n", namespace])
    result = _run_command(cmd)
    if result["success"]:
        try:
            result["data"] = json.loads(result["output"])
        except json.JSONDecodeError:
            pass
    return result

@mcp.tool()
def get_services(namespace: Optional[str] = None) -> dict:
    """获取集群中的Service信息
    Args:
        namespace: 命名空间
    Returns:
        dict: 包含执行结果的字典，成功时包含data字段，包含Service信息的JSON数据
    """
    cmd = [global_config['KUBECTL_PATH'], "get", "services", "-o", "json"]
    if namespace:
        cmd.extend(["-n", namespace])
    result = _run_command(cmd)
    if result["success"]:
        try:
            result["data"] = json.loads(result["output"])
        except json.JSONDecodeError:
            pass
    return result

@mcp.tool()
def apply_manifest(manifest_path: str) -> dict:
    """应用Kubernetes manifest文件
    Args:
        manifest_path: Kubernetes manifest文件路径
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    cmd = [global_config['KUBECTL_PATH'], "apply", "-f", manifest_path]
    return _run_command(cmd)

@mcp.tool()
def delete_resource(
    resource_type: str,
    resource_name: str,
    namespace: Optional[str] = None
) -> dict:
    """删除指定的Kubernetes资源   
    Args:
        resource_type: 资源类型，如pod, service, deployment等
        resource_name: 资源名称
        namespace: 命名空间 
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    cmd = [global_config['KUBECTL_PATH'], "delete", resource_type, resource_name]
    if namespace:
        cmd.extend(["-n", namespace])
    return _run_command(cmd)

@mcp.tool()
def get_logs(
    pod_name: str,
    namespace: Optional[str] = None,
    container: Optional[str] = None
) -> dict:
    """获取Pod的日志
    Args:
        pod_name: Pod名称
        namespace: 命名空间
        container: 容器名称，当Pod包含多个容器时指定
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    cmd = [global_config['KUBECTL_PATH'], "logs", pod_name]
    if namespace:
        cmd.extend(["-n", namespace])
    if container:
        cmd.extend(["-c", container])
    return _run_command(cmd)

@mcp.tool()
def scale_deployment(
    deployment_name: str,
    replicas: int,
    namespace: Optional[str] = None
) -> dict:
    """扩缩容Deployment
    Args:
        deployment_name: Deployment名称
        replicas: 副本数量
        namespace: 命名空间
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    cmd = [global_config['KUBECTL_PATH'], "scale", "deployment", deployment_name, f"--replicas={replicas}"]
    if namespace:
        cmd.extend(["-n", namespace])
    return _run_command(cmd)

@mcp.tool()
def k3s_install(config_file: str) -> dict:
    """使用k3sctl安装K3s集群
    Args:
        config_file: k3sctl配置文件路径
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    cmd = [global_config['K3SCTL_PATH'], "apply", "--config", config_file]
    return _run_command(cmd)

@mcp.tool()
def k3s_remove(config_file: str) -> dict:
    """使用k3sctl移除K3s集群
    Args:
        config_file: k3sctl配置文件路径
    Returns:
        dict: 包含执行结果的字典，包括success、output和error字段
    """
    cmd = [global_config['K3SCTL_PATH'], "delete", "--config", config_file]
    return _run_command(cmd)

if __name__ == "__main__":
    mcp.run()