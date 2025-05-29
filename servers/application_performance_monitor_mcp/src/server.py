#!/usr/bin/env python3
from pydantic import Field
from typing import Optional, Dict, Any
from mcp.server.fastmcp import FastMCP
import requests
import argparse
import os
import logging
from typing import List

mcp = FastMCP("applicationPerformanceMonitor")

class AppMetricsRequest:
    app_name: str = Field(..., description="应用程序名称")
    time_range: str = Field(default="5m", description="时间范围，如5m,1h等")

class SetupMonitoringRequest:
    app_name: str = Field(..., description="应用程序名称")
    port: int = Field(default=9090, description="监控端口")

global_config = {
    'PROMETHEUS_URL': None,
    'GRAFANA_URL': None
}

@mcp.tool()
def get_metrics(
    app_name: str = Field(..., description="应用程序名称"),
    time_range: str = Field(default="5m", description="时间范围，如5m,1h等")
) -> Dict[str, Any]:
    """获取应用程序性能指标"""
    try:
        query = f'sum(rate(container_cpu_usage_seconds_total{{name="{app_name}"}}[{time_range}])) by (name)'
        response = requests.get(
            f"{global_config['PROMETHEUS_URL']}/api/v1/query",
            params={'query': query}
        )
        return {"result": response.json()}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def setup_monitoring(
    app_name: str = Field(..., description="应用程序名称"),
    port: int = Field(default=9090, description="监控端口")
) -> Dict[str, Any]:
    """设置应用程序性能监控"""
    try:
        # 配置Prometheus监控
        prom_config = {
            "targets": [f"{app_name}:{port}"],
            "labels": {"job": app_name}
        }
        
        # 配置Grafana仪表板
        dashboard = {
            "title": f"{app_name} Performance",
            "panels": [
                {
                    "title": "CPU Usage",
                    "targets": [{"expr": f"rate(container_cpu_usage_seconds_total{{name='{app_name}'}}[5m])"}]
                }
            ]
        }
        
        return {
            "prometheus": prom_config,
            "grafana": dashboard
        }
    except Exception as e:
        return {"error": str(e)}

def init_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--PROMETHEUS_URL', required=True, help="Prometheus服务URL")
    parser.add_argument('--GRAFANA_URL', required=True, help="Grafana服务URL")
    
    args = parser.parse_args()
    
    global global_config
    global_config.update({
        'PROMETHEUS_URL': args.PROMETHEUS_URL,
        'GRAFANA_URL': args.GRAFANA_URL
    })
    
    # 初始化日志配置
    logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    init_config()
    mcp.run()