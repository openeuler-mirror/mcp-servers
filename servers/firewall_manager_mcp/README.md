# 防火墙管理MCP服务器

## 功能简介
提供对firewalld防火墙规则的查看和管理功能，包括：
- 查看防火墙状态
- 管理端口规则（添加/删除）
- 重新加载防火墙配置

## 使用说明

### 获取防火墙状态
```json
{
  "tool": "get_status"
}
```

### 列出开放端口
```json
{
  "tool": "list_ports",
  "zone": "public"  // 可选参数
}
```

### 添加端口规则
```json
{
  "tool": "add_port",
  "port": "8080",
  "protocol": "tcp",
  "zone": "public"  // 可选参数
}
```

### 删除端口规则
```json
{
  "tool": "remove_port", 
  "port": "8080",
  "protocol": "tcp",
  "zone": "public"  // 可选参数
}
```

### 重新加载配置
```json
{
  "tool": "reload_firewall"
}
```

## 注意事项
1. 需要系统安装并运行firewalld服务
2. 所有修改操作需要--permanent参数
3. 修改后需要执行reload_firewall使更改生效
4. 需要root权限执行firewall-cmd命令