# SSH Manager MCP

## 功能描述
提供SSH连接管理和SCP文件传输功能的MCP服务器

## 主要功能
- SSH连接建立
- SCP文件传输
- 支持密钥认证
- 支持自定义端口

## 使用方法

### SSH连接
```json
{
  "action": "ssh_connect",
  "host": "example.com",
  "username": "user",
  "port": 22,
  "key_path": "/path/to/key.pem"
}
```

### SCP文件传输
```json
{
  "action": "scp_transfer",
  "source": "local/file.txt",
  "destination": "user@remote:/path/to/dest",
  "recursive": false
}
```

## 依赖
- openssh-client
- sshpass (可选，用于密码认证)