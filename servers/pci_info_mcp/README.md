# PCI设备信息MCP服务器

## 功能描述
提供查询PCI设备信息的MCP工具，包括：
- 获取详细PCI设备信息
- 列出所有PCI设备

## 依赖
- pciutils (提供lspci命令)
- python3
- uv

## 使用方法
```bash
# 通过MCP客户端调用
mcp call pci_info_mcp get_pci_info
mcp call pci_info_mcp list_pci_devices
```

## 示例输出
```json
{
  "status": "success",
  "data": "00:00.0 \"Host bridge\" \"Intel Corporation\" ..."
}
```

## 打包说明
使用项目根目录的generate-mcp-spec.py生成RPM spec文件