# 中间件管理MCP服务

## 简介

中间件管理MCP服务（Middleware Manager MCP Server）提供了对系统中常见中间件的管理功能，包括状态监控、启动/停止/重启服务、查看配置文件和日志等功能。

## 支持的中间件

- Redis
- Kafka
- RabbitMQ
- MySQL
- PostgreSQL
- MongoDB
- Elasticsearch
- Nginx
- Apache2
- Memcached

## 功能列表

### 1. 列出中间件
- **功能**：列出系统中常见的中间件及其状态
- **方法**：`list_middleware`
- **参数**：无
- **返回**：中间件列表及其状态

### 2. 获取中间件状态
- **功能**：获取指定中间件的状态
- **方法**：`get_middleware_status`
- **参数**：
  - `middleware_name`：中间件名称
- **返回**：中间件状态

### 3. 启动中间件
- **功能**：启动指定的中间件服务
- **方法**：`start_middleware`
- **参数**：
  - `middleware_name`：中间件名称
- **返回**：启动结果

### 4. 停止中间件
- **功能**：停止指定的中间件服务
- **方法**：`stop_middleware`
- **参数**：
  - `middleware_name`：中间件名称
- **返回**：停止结果

### 5. 重启中间件
- **功能**：重启指定的中间件服务
- **方法**：`restart_middleware`
- **参数**：
  - `middleware_name`：中间件名称
- **返回**：重启结果

### 6. 获取中间件信息
- **功能**：获取指定中间件的详细信息，包括版本、配置文件位置等
- **方法**：`get_middleware_info`
- **参数**：
  - `middleware_name`：中间件名称
- **返回**：中间件详细信息（JSON格式）

### 7. 查看中间件配置
- **功能**：查看中间件的配置文件内容
- **方法**：`view_middleware_config`
- **参数**：
  - `middleware_name`：中间件名称
  - `config_path`：配置文件路径（可选）
- **返回**：配置文件内容

### 8. 查看中间件日志
- **功能**：查看中间件的日志文件
- **方法**：`get_middleware_logs`
- **参数**：
  - `middleware_name`：中间件名称
  - `lines`：要查看的日志行数（默认为50）
- **返回**：日志内容

## 安装与配置

1. 确保系统已安装Python 3.6+和uv
2. 安装依赖：`pip install -r src/requirements.txt`
3. 配置mcp_config.json文件
4. 将服务添加到MCP服务列表

## 使用示例

### 示例1：列出所有中间件及其状态
```python
from mcp.client import MCPClient

client = MCPClient()
result = client.call("middleware_manager_mcp", "list_middleware")
print(result)
```

### 示例2：启动Redis服务
```python
from mcp.client import MCPClient

client = MCPClient()
result = client.call("middleware_manager_mcp", "start_middleware", middleware_name="redis")
print(result)
```

### 示例3：查看Nginx配置文件
```python
from mcp.client import MCPClient

client = MCPClient()
result = client.call("middleware_manager_mcp", "view_middleware_config", middleware_name="nginx")
print(result)
```

## 注意事项

1. 部分操作可能需要管理员/root权限
2. 不同系统（Windows/Linux）的服务管理命令可能不同
3. 确保中间件已正确安装在系统中
4. 配置文件和日志文件路径可能因系统而异