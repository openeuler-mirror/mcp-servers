import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("网络流量监控服务")

@mcp.tool()
def monitor_traffic(interface: str = "eth0") -> str:
    """监控指定接口的网络流量(默认eth0)"""
    try:
        result = subprocess.check_output(
            ['iftop', '-i', interface, '-n', '-t', '-s', '1'],
            stderr=subprocess.STDOUT,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        return f"监控失败: {e.output}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool() 
def show_connections() -> str:
    """显示当前网络连接和带宽使用情况"""
    try:
        result = subprocess.check_output(
            ['nethogs', '-t', '-v', '3'],
            stderr=subprocess.STDOUT,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        return f"获取连接失败: {e.output}"
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def get_bandwidth(interface: str = "eth0") -> str:
    """获取指定接口的带宽使用情况(默认eth0)"""
    try:
        result = subprocess.check_output(
            ['iftop', '-i', interface, '-n', '-t', '-s', '1', '-L', '1'],
            stderr=subprocess.STDOUT,
            text=True
        )
        return result.splitlines()[-3:]  # 返回最后三行带宽统计信息
    except subprocess.CalledProcessError as e:
        return f"获取带宽失败: {e.output}"
    except Exception as e:
        return f"错误: {str(e)}"

if __name__ == "__main__":
    mcp.run()