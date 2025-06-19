# LTO分析工具MCP服务器

基于lto-dump命令的MCP服务器，提供LTO(链接时优化)分析功能。

## 功能

- 显示LTO摘要信息
- 列出符号表
- 显示IR代码
- 分析优化信息

## 安装

1. 确保已安装llvm工具链：
   ```bash
   sudo yum install llvm
   ```

2. 安装Python依赖：
   ```bash
   pip install -r src/requirements.txt
   ```

## 使用示例

```bash
# 显示LTO摘要信息
mcp lto-dump-mcp show_lto_summary --input_file /path/to/file.o

# 列出符号表
mcp lto-dump-mcp list_symbols --input_file /path/to/file.o

# 显示IR代码
mcp lto-dump-mcp show_ir_code --input_file /path/to/file.o

# 分析优化信息
mcp lto-dump-mcp analyze_optimizations --input_file /path/to/file.o
```

## 工具函数说明

- `show_lto_summary(input_file)`: 显示LTO摘要信息
- `list_symbols(input_file)`: 列出LTO符号表
- `show_ir_code(input_file)`: 显示LTO IR代码
- `analyze_optimizations(input_file)`: 分析LTO优化信息