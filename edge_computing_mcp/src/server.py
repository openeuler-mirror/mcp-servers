from pydantic import Field
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP
import json
import os

mcp = FastMCP("edge_computing_mcp")

@mcp.tool()
def list_edge_devices() -> str:
    """列出所有边缘设备"""
    devices = [
        {"id": "edge-001", "name": "Edge Gateway 1", "type": "Gateway", "status": "online", "location": "Factory Floor 1"},
        {"id": "edge-002", "name": "Edge Gateway 2", "type": "Gateway", "status": "online", "location": "Factory Floor 2"},
        {"id": "edge-003", "name": "IoT Sensor Hub", "type": "Sensor", "status": "online", "location": "Warehouse A"},
        {"id": "edge-004", "name": "Camera Node", "type": "Camera", "status": "offline", "location": "Security Gate"},
        {"id": "edge-005", "name": "Temperature Sensor", "type": "Sensor", "status": "online", "location": "Server Room"}
    ]
    return json.dumps(devices, ensure_ascii=False, indent=2)

@mcp.tool()
def add_edge_device(
    name: str = Field(description="设备名称"),
    device_type: str = Field(description="设备类型"),
    location: str = Field(description="设备位置"),
    config: Optional[Dict[str, Any]] = Field(default=None, description="设备配置")
) -> str:
    """添加新的边缘设备"""
    try:
        device_id = f"edge-{len(list_edge_devices()) + 1:03d}"
        response = {
            "status": "success",
            "device_id": device_id,
            "name": name,
            "type": device_type,
            "location": location,
            "config": config or {},
            "status": "offline"
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"添加设备失败: {str(e)}"

@mcp.tool()
def remove_edge_device(
    device_id: str = Field(description="设备ID")
) -> str:
    """移除边缘设备"""
    try:
        response = {
            "status": "success",
            "device_id": device_id,
            "message": "设备移除成功"
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"移除设备失败: {str(e)}"

@mcp.tool()
def get_edge_device_info(
    device_id: str = Field(description="设备ID")
) -> str:
    """获取边缘设备信息"""
    try:
        response = {
            "status": "success",
            "device_id": device_id,
            "name": "Edge Gateway",
            "type": "Gateway",
            "status": "online",
            "location": "Factory Floor",
            "ip_address": "192.168.1.100",
            "mac_address": "00:11:22:33:44:55",
            "cpu_usage": "45%",
            "memory_usage": "60%",
            "disk_usage": "30%",
            "last_heartbeat": "2026-03-30T19:00:00Z"
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取设备信息失败: {str(e)}"

@mcp.tool()
def update_edge_device_config(
    device_id: str = Field(description="设备ID"),
    config: Dict[str, Any] = Field(description="更新的配置")
) -> str:
    """更新边缘设备配置"""
    try:
        response = {
            "status": "success",
            "device_id": device_id,
            "updated_config": config,
            "message": "设备配置更新成功"
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"更新设备配置失败: {str(e)}"

@mcp.tool()
def restart_edge_device(
    device_id: str = Field(description="设备ID")
) -> str:
    """重启边缘设备"""
    try:
        response = {
            "status": "success",
            "device_id": device_id,
            "message": "设备重启命令已发送"
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"重启设备失败: {str(e)}"

@mcp.tool()
def deploy_edge_application(
    device_id: str = Field(description="设备ID"),
    app_name: str = Field(description="应用名称"),
    version: str = Field(description="应用版本"),
    config: Optional[Dict[str, Any]] = Field(default=None, description="应用配置")
) -> str:
    """在边缘设备上部署应用"""
    try:
        response = {
            "status": "success",
            "device_id": device_id,
            "app_name": app_name,
            "version": version,
            "config": config or {},
            "message": "应用部署成功"
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"部署应用失败: {str(e)}"

@mcp.tool()
def list_edge_applications(
    device_id: str = Field(description="设备ID")
) -> str:
    """列出边缘设备上的应用"""
    try:
        applications = [
            {"name": "Temperature Monitor", "version": "1.0.0", "status": "running"},
            {"name": "Video Analytics", "version": "2.1.0", "status": "running"},
            {"name": "Data Collector", "version": "1.5.0", "status": "stopped"}
        ]
        response = {
            "status": "success",
            "device_id": device_id,
            "applications": applications
        }
        return json.dumps(response, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取应用列表失败: {str(e)}"

@mcp.tool()
def get_edge_network_status() -> str:
    """获取边缘网络状态"""
    try:
        network_status = {
            "status": "online",
            "devices_online": 4,
            "devices_offline": 1,
            "network_latency": "10ms",
            "bandwidth_usage": "45%",
            "last_updated": "2026-03-30T19:00:00Z"
        }
        return json.dumps(network_status, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取网络状态失败: {str(e)}"

if __name__ == "__main__":
    mcp.run()