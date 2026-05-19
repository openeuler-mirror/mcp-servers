# Network Performance Analysis MCP Service

## Function Description

It provides the network bandwidth and throughput test functions, which are implemented based on iperf and netperf.

## Dependencies

- System dependencies: iperf and netperf
- Python dependency: fastmcp

## How to Use

### Testing the Network Bandwidth

```json
{
  "tool": "test_bandwidth",
  "target": "IP address of the target host",
  "duration": test duration (in seconds)
}
```

### Testing the Network Throughput

```json
{
  "tool": "test_throughput", 
  "target": "IP address of the target host",
  "duration": test duration (in seconds)
}
```

## Returned Results

- Bandwidth test result:
  - bandwidth: bandwidth (Mbit/s)
  - retransmits: number of retransmissions

- Throughput test result:
  - throughput: throughput (transactions/sec)
  - latency: average latency (ms)

## Installation Description

1. Ensure that iperf and netperf have been installed.
2. Install the service using the RPM package.
3. The service automatically starts and listens on the specified port.
