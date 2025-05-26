import os
import subprocess
import json
import time
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("HTTP测试工具")

def execute_http_request(method, url, data=None, json_data=None, headers=None, tool='curl'):
    """执行HTTP请求并返回结构化结果"""
    start_time = time.time()
    result = {
        "status_code": None,
        "headers": {},
        "content": "",
        "elapsed": 0,
        "error": None
    }

    try:
        if tool == 'curl':
            cmd = ["curl", "-s", "-X", method.upper(), url]
            if headers:
                for k, v in headers.items():
                    cmd.extend(["-H", f"{k}: {v}"])
            if json_data:
                cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(json_data)])
            elif data:
                cmd.extend(["-d", str(data)])
            
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            result["content"] = output

        elif tool == 'httpie':
            cmd = ["http", method.upper(), url]
            if headers:
                for k, v in headers.items():
                    cmd.append(f"{k}:{v}")
            if json_data:
                cmd.append(f"json:={json.dumps(json_data)}")
            elif data:
                cmd.append(f"form:={data}")
            
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            result["content"] = output

        result["status_code"] = 200  # 简化处理，实际应从输出中解析
        result["elapsed"] = time.time() - start_time

    except subprocess.CalledProcessError as e:
        result["error"] = str(e)
        result["content"] = e.output
    except Exception as e:
        result["error"] = str(e)
    
    return result

@mcp.tool()
def get(url: str, params: dict = None, headers: dict = None) -> dict:
    """发送GET请求"""
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return execute_http_request("GET", url, headers=headers)

@mcp.tool()
def post(url: str, data: dict = None, json_data: dict = None, headers: dict = None) -> dict:
    """发送POST请求"""
    return execute_http_request("POST", url, data=data, json_data=json_data, headers=headers)

@mcp.tool()
def put(url: str, data: dict = None, json_data: dict = None, headers: dict = None) -> dict:
    """发送PUT请求"""
    return execute_http_request("PUT", url, data=data, json_data=json_data, headers=headers)

@mcp.tool()
def delete(url: str, headers: dict = None) -> dict:
    """发送DELETE请求"""
    return execute_http_request("DELETE", url, headers=headers)

@mcp.tool()
def request(method: str, url: str, **kwargs) -> dict:
    """发送自定义HTTP请求"""
    return execute_http_request(method, url, **kwargs)

if __name__ == "__main__":
    mcp.run()