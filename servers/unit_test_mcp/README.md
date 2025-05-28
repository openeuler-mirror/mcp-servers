# Unit Test MCP Server

## 功能说明

提供单元测试执行和结果分析功能，支持以下测试框架:
- Google Test (gtest)
- Python pytest
- JUnit

## 使用方法

1. 确保已安装MCP客户端(如Roo Code)
2. 将本MCP Server添加到客户端配置
3. 调用以下工具:

### run_gtest
执行gtest测试并返回结果

参数:
- test_binary: gtest测试可执行文件路径

示例:
```json
{
  "tool": "run_gtest",
  "params": {
    "test_binary": "/path/to/test_binary"
  }
}
```

### run_pytest
执行pytest测试并返回结果

参数:
- test_dir: 包含pytest测试的目录路径

示例:
```json
{
  "tool": "run_pytest", 
  "params": {
    "test_dir": "/path/to/tests"
  }
}
```

### run_junit
执行JUnit测试并返回结果

参数:
- test_command: 执行测试的命令
- xml_output: JUnit XML输出文件路径

示例:
```json
{
  "tool": "run_junit",
  "params": {
    "test_command": "mvn test",
    "xml_output": "target/surefire-reports/TEST-*.xml"
  }
}
```

## 依赖

- gtest-devel
- python3-pytest
- junit
- python3-mcp

## RPM打包

本MCP Server已配置为可打包为RPM:
```bash
python3 generate-mcp-spec.py
rpmbuild -ba mcp-servers.spec