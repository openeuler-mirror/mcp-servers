import subprocess
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("网络性能分析服务")

@mcp.tool()
def test_bandwidth(target: str, duration: int = 10) -> dict:
    """
    测试网络带宽
    
    参数:
        target: 目标主机名或IP地址
        duration: 测试持续时间(秒)，默认10秒
        
    返回:
        包含带宽测试结果的字典:
        - bandwidth: 带宽(Mbps)
        - retransmits: 重传次数
    """
    try:
        # 调用iperf进行带宽测试
        cmd = f"iperf -c {target} -t {duration} -f m -J"
        result = subprocess.check_output(cmd, shell=True, text=True)
        
        data = json.loads(result)
        return {
            "target": target,
            "bandwidth": data["end"]["sum_sent"]["bits_per_second"] / 1e6,
            "retransmits": data["end"]["sum_sent"]["retransmits"]
        }
        
    except subprocess.CalledProcessError as e:
        return {"error": f"iperf执行失败: {str(e)}"}
    except json.JSONDecodeError as e:
        return {"error": f"结果解析失败: {str(e)}"}
    except Exception as e:
        return {"error": f"带宽测试错误: {str(e)}"}

@mcp.tool()
def test_throughput(target: str, duration: int = 10) -> dict:
    """
    测试网络吞吐量
    
    参数:
        target: 目标主机名或IP地址
        duration: 测试持续时间(秒)，默认10秒
        
    返回:
        包含吞吐量测试结果的字典:
        - throughput: 吞吐量(transactions/sec)
        - latency: 平均延迟(ms)
    """
    try:
        # 调用netperf进行吞吐量测试
        cmd = f"netperf -H {target} -l {duration} -t TCP_RR -- -o throughput"
        result = subprocess.check_output(cmd, shell=True, text=True)
        
        # 解析netperf输出
        throughput = float(result.splitlines()[-1].split()[-1])
        latency = float(result.splitlines()[-2].split()[-1])
        
        return {
            "target": target,
            "throughput": throughput,
            "latency": latency
        }
        
    except subprocess.CalledProcessError as e:
        return {"error": f"netperf执行失败: {str(e)}"}
    except Exception as e:
        return {"error": f"吞吐量测试错误: {str(e)}"}

if __name__ == "__main__":
    mcp.run()