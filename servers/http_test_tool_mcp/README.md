# HTTP测试工具MCP服务器

## 功能描述
封装HTTP请求功能，支持GET/POST/PUT/DELETE等常用HTTP方法，提供简洁的API接口。

## 依赖要求
- 系统依赖: curl, httpie
- Python依赖: requests

## 安装方法
1. 确保已安装依赖:
```bash
dnf install curl httpie python3-requests
```

2. 通过MCP安装:
```bash
mcp install http_test_tool_mcp
```

## 使用示例
```python
# 发送GET请求
response = mcp.http_test_tool.get("https://api.example.com/data")

# 发送POST请求
response = mcp.http_test_tool.post(
    "https://api.example.com/data",
    json={"key": "value"},
    headers={"Content-Type": "application/json"}
)
```

## API接口
- `get(url, params=None, headers=None)`: 发送GET请求
- `post(url, data=None, json=None, headers=None)`: 发送POST请求  
- `put(url, data=None, json=None, headers=None)`: 发送PUT请求
- `delete(url, headers=None)`: 发送DELETE请求
- `request(method, url, **kwargs)`: 发送自定义HTTP请求

所有方法返回包含以下字段的字典:
- `status_code`: HTTP状态码
- `headers`: 响应头
- `content`: 响应内容
- `elapsed`: 请求耗时(秒)