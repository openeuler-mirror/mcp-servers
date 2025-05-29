# 容器编排工具MCP Server

## 功能描述
提供基于docker-compose的容器编排管理功能，包括：
- 启动/停止容器服务
- 管理docker-compose配置

## 安装要求
- Docker Engine
- docker-compose
- Python 3.6+

## 使用方法

1. 安装依赖：
```bash
pip install -r src/requirements.txt
```

2. 启动服务：
```bash
python src/server.py
```

## API接口

### 启动服务
POST /compose/up
```json
{
  "compose_file": "docker-compose.yml"
}
```

### 停止服务 
POST /compose/down
```json
{
  "compose_file": "docker-compose.yml"
}
```

## 打包说明
本MCP Server已配置RPM打包支持，可直接使用项目根目录的打包脚本生成RPM包。