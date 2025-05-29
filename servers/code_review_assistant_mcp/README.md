# 代码审查助手 MCP Server

## 功能描述

提供自动化代码审查功能，支持以下语言的静态分析：

- C/C++ (使用cppcheck)
- Python (使用pylint)

## 安装依赖

```bash
yum install cppcheck pylint python3-pylint
```

## 使用方法

1. 通过MCP客户端配置服务：
```json
{
  "mcpServers": {
    "code_review_assistant": {
      "command": "python3",
      "args": ["src/server.py"],
      "disabled": false
    }
  }
}
```

2. 调用代码审查接口：
```python
# 审查单个文件
result = mcp.call("code_review_assistant", "analyze_code", {"file_path": "/path/to/file"})

# 批量审查目录
result = mcp.call("code_review_assistant", "analyze_directory", {"dir_path": "/path/to/dir"})
```

## 输出格式

返回JSON格式的分析结果，包含：
- 问题类型
- 问题描述
- 严重级别
- 位置信息

## 示例输出

```json
{
  "issues": [
    {
      "type": "warning",
      "message": "Unused variable 'x'",
      "severity": "medium",
      "location": "file.py:10"
    }
  ]
}