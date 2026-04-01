# 边缘计算管理MCP服务

## 简介

边缘计算管理MCP服务是一个提供边缘设备和应用管理功能的MCP服务，支持边缘设备的注册、配置、监控和维护，以及边缘应用的部署和管理。

## 功能特性

- 列出所有边缘设备
- 添加新的边缘设备
- 移除边缘设备
- 获取边缘设备信息
- 更新边缘设备配置
- 重启边缘设备
- 在边缘设备上部署应用
- 列出边缘设备上的应用
- 获取边缘网络状态

## 安装方法

1. 克隆代码仓库
2. 进入 `edge_computing_mcp` 目录
3. 安装依赖：
   ```bash
   pip install -r src/requirements.txt
   ```
4. 运行服务：
   ```bash
   python src/server.py
   ```

## 使用方法

### 列出所有边缘设备

```bash
mcp call edge_computing_mcp list_edge_devices
```

### 添加新的边缘设备

```bash
mcp call edge_computing_mcp add_edge_device --name "New Edge Gateway" --device_type "Gateway" --location "Factory Floor 3" --config '{"ip_range": "192.168.1.101/24", "gateway": "192.168.1.1"}'
```

### 移除边缘设备

```bash
mcp call edge_computing_mcp remove_edge_device --device_id "edge-004"
```

### 获取边缘设备信息

```bash
mcp call edge_computing_mcp get_edge_device_info --device_id "edge-001"
```

### 更新边缘设备配置

```bash
mcp call edge_computing_mcp update_edge_device_config --device_id "edge-001" --config '{"ip_range": "192.168.1.100/24", "gateway": "192.168.1.1"}'
```

### 重启边缘设备

```bash
mcp call edge_computing_mcp restart_edge_device --device_id "edge-001"
```

### 在边缘设备上部署应用

```bash
mcp call edge_computing_mcp deploy_edge_application --device_id "edge-001" --app_name "Temperature Monitor" --version "1.0.0" --config '{"interval": 60, "threshold": 30}'
```

### 列出边缘设备上的应用

```bash
mcp call edge_computing_mcp list_edge_applications --device_id "edge-001"
```

### 获取边缘网络状态

```bash
mcp call edge_computing_mcp get_edge_network_status
```

## 配置文件

服务配置文件为 `mcp_config.json`，定义了服务的基本信息和命令。

## 打包部署

使用 `mcp-rpm.yaml` 文件进行打包，可生成RPM包进行部署。
