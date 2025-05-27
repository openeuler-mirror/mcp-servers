# 网络性能分析MCP服务

## 功能概述
提供网络带宽和吞吐量测试功能，基于iperf和netperf实现。

## 依赖要求
- 系统依赖: iperf, netperf
- Python依赖: fastmcp

## 使用方法

### 测试网络带宽
```json
{
  "tool": "test_bandwidth",
  "target": "目标主机IP",
  "duration": 测试持续时间(秒)
}
```

### 测试网络吞吐量
```json
{
  "tool": "test_throughput", 
  "target": "目标主机IP",
  "duration": 测试持续时间(秒)
}
```

## 返回结果
- 带宽测试返回:
  - bandwidth: 带宽(Mbps)
  - retransmits: 重传次数

- 吞吐量测试返回:
  - throughput: 吞吐量(transactions/sec)
  - latency: 平均延迟(ms)

## 安装说明
1. 确保已安装iperf和netperf
2. 通过RPM包安装本服务
3. 服务将自动启动并监听指定端口