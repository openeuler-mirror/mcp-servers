import nmap
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("端口扫描服务")

@mcp.tool()
def scan_ports(target: str, ports: str = "1-1000") -> dict:
    """
    扫描目标主机的开放端口
    
    参数:
        target: 目标主机名或IP地址
        ports: 要扫描的端口范围(默认:1-1000)
        
    返回:
        包含开放端口信息的字典
    """
    try:
        nm = nmap.PortScanner()
        nm.scan(hosts=target, ports=ports)
        
        results = {}
        for host in nm.all_hosts():
            host_info = {
                "status": nm[host].state(),
                "ports": []
            }
            
            for proto in nm[host].all_protocols():
                ports_info = nm[host][proto]
                for port, info in ports_info.items():
                    host_info["ports"].append({
                        "port": port,
                        "state": info["state"],
                        "service": info["name"]
                    })
            
            results[host] = host_info
        
        return results
        
    except nmap.PortScannerError as e:
        return {"error": f"nmap扫描错误: {str(e)}"}
    except Exception as e:
        return {"error": f"扫描过程中发生错误: {str(e)}"}

if __name__ == "__main__":
    mcp.run()