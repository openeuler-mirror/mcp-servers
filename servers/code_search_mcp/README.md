# 代码搜索工具 MCP 服务器

## 功能
提供快速代码搜索功能，基于ripgrep(rg)实现。

## 使用方式
```json
{
  "tool": "code_search_mcp",
  "function": "search_code",
  "params": {
    "search_term": "要搜索的内容",
    "path": "搜索路径(可选，默认为当前目录)",
    "file_type": "文件类型过滤(可选，如.py,.js等)"
  }
}
```

## 示例
搜索当前目录下所有Python文件中的"import"语句：
```json
{
  "tool": "code_search_mcp",
  "function": "search_code",
  "params": {
    "search_term": "import",
    "file_type": "py"
  }
}
```

## 依赖
- ripgrep(rg): 必须安装
- ack: 可选(暂未实现)

## 安装
```bash
# 安装ripgrep
sudo dnf install ripgrep