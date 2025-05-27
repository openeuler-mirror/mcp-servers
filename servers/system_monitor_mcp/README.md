# 系统监控MCP服务器

## 功能
监控系统资源使用情况，包括：
- CPU使用率
- 内存使用情况
- 磁盘使用情况

## 依赖
- 系统依赖: sysstat, htop
- Python依赖: 见src/requirements.txt

## 使用说明

### 可用命令
- `cpu_usage`: 获取CPU使用率
- `memory_usage`: 获取内存使用情况
- `disk_usage`: 获取磁盘使用情况

### 示例
```json
{
  "command": "cpu_usage",
  "args": {}
}
```

## 构建说明
参见项目根目录下的[MCP-Server-RPM打包指南](../doc/MCP-Server-RPM打包指南.md)