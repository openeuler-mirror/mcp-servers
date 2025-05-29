# 容器镜像转换MCP服务

## 功能描述
提供容器镜像格式转换和推送功能，支持以下操作：
- 镜像格式转换（docker ↔ oci）
- 镜像推送到远程仓库

## 依赖
- skopeo
- buildah
- jq

## 工具接口

### 镜像格式转换
```json
{
  "source": "docker://nginx:latest",
  "destination": "oci:/tmp/nginx:latest",
  "src_format": "docker",
  "dest_format": "oci"
}
```

### 推送镜像到仓库
```json
{
  "image": "nginx",
  "registry": "registry.example.com/library",
  "tag": "latest",
  "authfile": "/path/to/auth.json"
}
```

## 配置说明
修改`mcp_config.json`可调整默认参数：
- `--insecure-policy`: 允许不安全的镜像策略
- `--override-os`: 覆盖目标操作系统类型