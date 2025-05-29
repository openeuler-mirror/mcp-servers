# 编译诊断工具MCP服务器

## 功能
分析gcc/clang编译错误和警告，提供结构化的诊断信息

## 依赖
- gcc
- clang
- Python 3
- uv

## 使用方法
1. 启动MCP服务器：
```bash
uv --directory /opt/mcp-servers/servers/compile_diagnostic_mcp/src run server.py
```

2. 调用分析接口：
```json
{
  "tool": "compile_diagnostic_mcp",
  "action": "analyze_compile_log",
  "input": {
    "log": "编译日志内容或文件路径"
  }
}
```

## 输出示例
```json
{
  "errors": [
    {
      "file": "example.c",
      "line": 10,
      "column": 5,
      "message": "expected ';' before '}' token",
      "type": "error"
    }
  ],
  "warnings": [
    {
      "file": "example.c", 
      "line": 5,
      "column": 1,
      "message": "unused variable 'x'",
      "type": "warning"
    }
  ]
}