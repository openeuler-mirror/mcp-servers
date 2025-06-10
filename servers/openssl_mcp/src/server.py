from pydantic import Field
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP
import subprocess
import argparse
import tempfile
import os

mcp = FastMCP("opensslCertificateManager")

@mcp.tool()
def generate_self_signed_cert(
    common_name: str = Field(..., description="证书通用名称(CN)"),
    days: int = Field(365, description="证书有效期(天)"),
    key_size: int = Field(2048, description="密钥长度(位)"),
    output_dir: Optional[str] = Field(None, description="输出目录路径")
) -> Dict[str, str]:
    """生成自签名证书
    
    示例用法:
    1. 生成一个CN为example.com的有效期1年的证书
    
    返回:
    {
        "status": str,  # 操作状态
        "message": str, # 详细信息
        "cert_path": str, # 证书路径
        "key_path": str   # 私钥路径
    }
    """
    try:
        if not output_dir:
            output_dir = tempfile.mkdtemp()
        
        key_path = os.path.join(output_dir, f"{common_name}.key")
        cert_path = os.path.join(output_dir, f"{common_name}.crt")
        
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", f"rsa:{key_size}",
            "-keyout", key_path, "-out", cert_path, "-days", str(days),
            "-nodes", "-subj", f"/CN={common_name}"
        ], check=True)
        
        return {
            "status": "success",
            "message": "Self-signed certificate generated",
            "cert_path": cert_path,
            "key_path": key_path
        }
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Failed to generate certificate: {e.stderr}"}

@mcp.tool()
def view_certificate(
    cert_path: str = Field(..., description="证书文件路径")
) -> Dict[str, str]:
    """查看证书信息
    
    返回:
    {
        "subject": str,  # 证书主题
        "issuer": str,   # 颁发者
        "valid_from": str, # 有效期开始
        "valid_until": str, # 有效期结束
        "serial": str     # 序列号
    }
    """
    try:
        result = subprocess.run([
            "openssl", "x509", "-in", cert_path, "-noout",
            "-subject", "-issuer", "-dates", "-serial"
        ], capture_output=True, text=True, check=True)
        
        info = {}
        for line in result.stdout.splitlines():
            if line.startswith("subject="):
                info["subject"] = line[8:]
            elif line.startswith("issuer="):
                info["issuer"] = line[7:]
            elif line.startswith("notBefore="):
                info["valid_from"] = line[10:]
            elif line.startswith("notAfter="):
                info["valid_until"] = line[9:]
            elif line.startswith("serial="):
                info["serial"] = line[7:]
                
        return info
    except subprocess.CalledProcessError as e:
        return {"error": f"Failed to view certificate: {e.stderr}"}

@mcp.tool()
def verify_certificate(
    cert_path: str = Field(..., description="证书文件路径"),
    ca_path: Optional[str] = Field(None, description="CA证书路径(可选)")
) -> Dict[str, str]:
    """验证证书
    
    返回:
    {
        "status": str,  # 验证状态
        "message": str  # 详细信息
    }
    """
    try:
        cmd = ["openssl", "verify"]
        if ca_path:
            cmd.extend(["-CAfile", ca_path])
        cmd.append(cert_path)
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"status": "success", "message": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": e.stderr.strip()}

@mcp.tool()
def convert_certificate(
    input_path: str = Field(..., description="输入文件路径"),
    output_path: str = Field(..., description="输出文件路径"),
    input_format: str = Field("PEM", description="输入格式(PEM/DER)"),
    output_format: str = Field("PEM", description="输出格式(PEM/DER)")
) -> Dict[str, str]:
    """转换证书格式
    
    返回:
    {
        "status": str,  # 操作状态
        "message": str  # 详细信息
    }
    """
    try:
        subprocess.run([
            "openssl", "x509", "-in", input_path, "-out", output_path,
            "-inform", input_format, "-outform", output_format
        ], check=True)
        return {"status": "success", "message": "Certificate converted"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Failed to convert certificate: {e.stderr}"}

if __name__ == "__main__":
    mcp.run()