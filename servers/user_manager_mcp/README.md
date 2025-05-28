# 用户管理MCP服务器

## 功能
- 添加用户
- 删除用户
- 修改用户信息

## 依赖
- shadow-utils (提供useradd/userdel/usermod命令)
- python3-mcp

## 使用说明

### 1. 安装
```bash
yum install mcp-user-manager
```

### 2. 配置
在MCP客户端配置文件中添加:
```json
{
  "user_manager_mcp": {
    "command": "uv",
    "args": [
      "--directory",
      "/opt/mcp-servers/servers/user_manager_mcp/src",
      "run",
      "server.py"
    ]
  }
}
```

### 3. 使用示例
- 添加用户:
```python
add_user("testuser", "password123")
```

- 删除用户:
```python 
delete_user("testuser")
```

- 修改用户:
```python
modify_user("testuser", new_name="newuser", password="newpass")
```

## 注意事项
- 需要sudo权限执行用户管理操作
- 密码修改需要交互式输入