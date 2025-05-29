# API文档生成MCP服务

## 功能

提供API文档生成工具，支持以下格式：
- Doxygen (支持C/C++/Python等)
- Sphinx (支持Python文档)

## 使用方法

1. 通过MCP客户端调用`generate_docs`工具：
```json
{
  "tool": "generate_docs",
  "project_path": "/path/to/project",
  "doc_type": "doxygen|sphinx"
}
```

2. 直接运行：
```bash
uv --directory /path/to/api_document_mcp/src run server.py
```

## 依赖

- doxygen
- sphinx
- python3-sphinx

## RPM安装

```bash
yum install mcp-api-document
```

安装后自动注册MCP服务。