# CMake测试工具MCP服务器

基于ctest命令的MCP服务器，提供CMake测试套件管理功能。

## 功能

- 运行CMake测试套件
- 列出所有可用测试
- 生成测试覆盖率报告
- 支持并行测试
- 支持测试过滤和超时设置

## 安装

1. 确保已安装CMake和ctest：
   ```bash
   sudo yum install cmake
   ```

2. 安装Python依赖：
   ```bash
   pip install -r src/requirements.txt
   ```

## 使用示例

```bash
# 运行所有测试
mcp ctest-mcp run_tests --build_dir /path/to/build_dir

# 运行特定测试
mcp ctest-mcp run_tests --build_dir /path/to/build_dir --tests test1 test2

# 并行运行测试
mcp ctest-mcp run_tests --build_dir /path/to/build_dir --parallel 4

# 列出所有测试
mcp ctest-mcp list_tests --build_dir /path/to/build_dir

# 生成覆盖率报告
mcp ctest-mcp test_coverage --build_dir /path/to/build_dir
```

## 工具函数说明

- `run_tests(build_dir, tests=None, parallel=None, output_on_failure=True, verbose=False, timeout=None)`: 运行CMake测试套件
- `list_tests(build_dir, verbose=False)`: 列出所有可用测试
- `test_coverage(build_dir, output_file=None)`: 生成测试覆盖率报告