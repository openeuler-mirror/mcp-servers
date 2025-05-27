# 网络监控MCP服务器

## 功能描述
提供网络流量监控功能，包括:
- 实时网络流量监控(基于iftop)
- 网络连接状态查看(基于nethogs) 
- 带宽使用统计

## 安装要求
```bash
yum install -y iftop nethogs
```

## 使用方法
1. 确保已安装iftop和nethogs工具
2. 通过MCP客户端调用以下功能:

```python
# 监控eth0接口流量
monitor_traffic(interface="eth0")

# 查看当前网络连接
show_connections()

# 获取eth0接口带宽使用情况
get_bandwidth(interface="eth0")
```

## 注意事项
1. 需要root权限运行iftop和nethogs
2. 默认监控eth0接口，可指定其他网络接口
3. 实时监控功能会持续1秒后返回结果