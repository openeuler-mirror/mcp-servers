# 应用性能监控MCP服务器

## 功能描述
本MCP服务器提供应用程序性能指标监控功能，集成Prometheus和Grafana实现：
- 实时性能指标采集
- 可视化监控面板
- 历史数据查询

## 依赖要求
- Prometheus 服务
- Grafana 服务
- Python 3.6+

## 使用方法
1. 确保已安装并运行Prometheus和Grafana
2. 启动MCP服务器：
```bash
python3 src/server.py
```

## 工具说明
### get_metrics
获取应用程序性能指标：
```json
{
  "app_name": "your_application",
  "time_range": "5m"
}
```

### setup_monitoring
设置应用程序监控：
```json
{
  "app_name": "your_application", 
  "port": 9090
}
```

## 配置说明
修改`mcp_config.json`可调整：
- 监控指标类型
- 默认时间范围
- Prometheus/Grafana连接地址