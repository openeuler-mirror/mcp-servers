# Kernel Tuner MCP Server

## 功能描述
提供通过MCP接口调整内核运行时参数的能力，基于sysctl命令实现。

## 依赖
- procps (包含sysctl命令)
- Python 3.6+
- Flask

## API接口

### 获取参数值
- 路径: `/get_param`
- 方法: POST
- 参数:
  ```json
  {
    "param": "kernel.hostname"
  }
  ```
- 响应:
  ```json
  {
    "value": "myhost"
  }
  ```

### 设置参数值
- 路径: `/set_param` 
- 方法: POST
- 参数:
  ```json
  {
    "param": "vm.swappiness",
    "value": "10"
  }
  ```
- 响应:
  ```json
  {
    "status": "success"
  }
  ```

### 列出所有参数
- 路径: `/list_params`
- 方法: GET
- 响应:
  ```json
  {
    "params": [
      "kernel.hostname",
      "vm.swappiness",
      "..."
    ]
  }
  ```

## 注意事项
1. 需要root权限才能修改内核参数
2. 修改某些参数可能导致系统不稳定
3. 参数名称需符合正则: `^[a-zA-Z0-9_.-]+$`