# 系统资源限制MCP服务器

## 功能描述
管理系统资源限制配置，通过修改`/etc/security/limits.conf`文件实现对系统资源限制的管理。

## 依赖
- pam_limits
- python3
- uv
- python3-mcp

## 使用方法
1. 确保已安装所有依赖
2. 启动MCP服务器
3. 通过MCP客户端调用提供的工具接口

## 提供的工具接口
- `get_limits()`: 获取当前系统资源限制配置
- `set_limits(domain, type, item, value)`: 设置指定域的资源限制
- `add_limit(domain, type, item, value)`: 添加新的资源限制
- `remove_limit(domain, item)`: 移除指定域的资源限制

## 参数说明
- `domain`: 用户/组名，如"*"表示所有用户，"root"表示root用户
- `type`: 限制类型，"hard"或"soft"
- `item`: 限制项，如"nofile"(文件描述符数量),"nproc"(进程数)等
- `value`: 限制值

## 注意事项
1. 修改limits.conf需要root权限
2. 每次修改前会自动创建备份文件`limits.conf.bak`
3. 修改后需要重新登录用户或重启服务生效