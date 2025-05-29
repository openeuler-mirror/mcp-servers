# USB设备监控MCP服务器

## 功能描述
监控USB设备连接状态，通过调用`lsusb`命令获取USB设备信息并返回标准化结果。

## 依赖
- 系统依赖: usbutils
- Python依赖: 无额外依赖(使用Python标准库)

## 安装
1. 确保已安装usbutils:
   ```bash
   sudo dnf install usbutils
   ```
2. 通过RPM安装MCP服务器:
   ```bash
   sudo rpm -ivh usb-monitor-mcp-1.0.0.rpm
   ```

## 使用示例
### 请求
```json
{
  "method": "get_usb_devices"
}
```

### 响应
```json
{
  "devices": [
    "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub",
    "Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub"
  ]
}
```

## 错误处理
如果发生错误，响应将包含error字段:
```json
{
  "error": "错误描述信息"
}
```

## 维护
- 版本: 1.0.0
- 维护者: openEuler社区