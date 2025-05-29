# 缓存管理工具MCP Server

## 功能描述
提供Redis和Memcached缓存系统的管理功能，支持执行各种缓存操作命令。

## 依赖要求
- Redis服务已安装并运行
- Memcached服务已安装并运行
- Python 3.6+

## 使用方法

### Redis命令执行
```json
{
  "tool": "redis",
  "parameters": {
    "command": "get key_name"
  }
}
```

### Memcached命令执行
```json
{
  "tool": "memcached", 
  "parameters": {
    "command": "stats"
  }
}
```

## 示例命令
- Redis设置值: `SET mykey "Hello"`
- Redis获取值: `GET mykey`
- Memcached设置值: `set mykey 0 0 5\r\nHello`
- Memcached获取状态: `stats`

## 注意事项
1. 确保Redis和Memcached服务已启动
2. 复杂命令请使用引号包裹
3. 默认连接本地服务(127.0.0.1)