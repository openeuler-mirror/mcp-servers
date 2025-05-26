# 硬件信息查询MCP服务器

## 功能描述
提供系统硬件信息查询功能，包括：
- CPU信息
- 内存信息
- 磁盘信息
- 网络设备信息
- BIOS信息

## 依赖
- 系统依赖: lshw, dmidecode
- Python依赖: 无

## 使用示例
```bash
# 查询完整硬件信息
mcp-tool hardware_info_mcp get_hardware_info

# 查询CPU信息
mcp-tool hardware_info_mcp get_cpu_info

# 查询内存信息
mcp-tool hardware_info_mcp get_memory_info
```

## 注意事项
1. 需要root权限才能获取完整的硬件信息
2. 确保系统已安装lshw和dmidecode工具
3. 部分信息可能因硬件差异而有所不同