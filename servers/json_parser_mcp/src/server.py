#!/usr/bin/env python3
from pydantic import Field
from typing import Dict, Any, Optional, Union
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import argparse
import os
from pathlib import Path

mcp = FastMCP("jsonParserMcp")

@mcp.tool()
def format_json(
    input_data: Union[str, Dict[str, Any]] = Field(..., description="要格式化的JSON字符串或字典"),
    indent: int = Field(default=2, ge=0, le=8, description="缩进空格数 (0-8)"),
    sort_keys: bool = Field(default=False, description="是否按键名排序")
) -> Dict[str, Any]:
    """格式化JSON数据
    
    示例用法:
    1. 格式化JSON字符串: format_json input_data='{"name":"John","age":30}'
    2. 带缩进和排序: format_json input_data='{"b":2,"a":1}' indent=4 sort_keys=true
    """
    # 输入校验
    if not input_data:
        return {"success": False, "error": "输入数据不能为空"}
    
    # 预处理输入数据
    if isinstance(input_data, str):
        if not input_data.strip():
            return {"success": False, "error": "JSON字符串不能为空"}
        try:
            data = json.loads(input_data)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"无效的JSON格式: {str(e)}"}
    else:
        data = input_data
    
    # 核心格式化逻辑
    try:
        formatted = json.dumps(
            data,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=False
        )
    except TypeError as e:
        return {"success": False, "error": f"数据序列化失败: {str(e)}"}
    
    return {"success": True, "formatted": formatted}

@mcp.tool()
def query_json(
    input_data: Union[str, Dict] = Field(..., description="要查询的JSON数据"),
    jq_filter: str = Field(..., description="jq过滤表达式"),
    raw_output: bool = Field(default=False, description="返回原始字符串而非JSON")
) -> Dict[str, Any]:
    """使用jq语法查询JSON数据
    
    示例用法:
    1. 获取所有名字: query_json input_data='{"users":[{"name":"John"}]}' jq_filter='.users[].name'
    2. 原始输出: query_json input_data='{"a":1}' jq_filter='.a' raw_output=true
    """
    try:
        if isinstance(input_data, dict):
            input_str = json.dumps(input_data)
        else:
            input_str = input_data
            
        cmd = ["jq", jq_filter]
        result = subprocess.run(
            cmd,
            input=input_str,
            capture_output=True,
            text=True,
            check=True
        )
        
        if raw_output:
            return {"success": True, "result": result.stdout.strip()}
        else:
            return {"success": True, "result": json.loads(result.stdout)}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": e.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def validate_json(
    input_data: str = Field(..., description="要验证的JSON字符串")
) -> Dict[str, Any]:
    """验证JSON格式是否正确
    
    示例用法:
    1. 验证JSON: validate_json input_data='{"valid":true}'
    """
    try:
        json.loads(input_data)
        return {"success": True}
    except json.JSONDecodeError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def convert_json(
    input_data: Union[str, Dict, List] = Field(..., description="输入数据"),
    to_format: str = Field(..., description="目标格式(csv, yaml, xml)"),
    options: Optional[Dict] = Field(default=None, description="转换选项")
) -> Dict[str, Any]:
    """将JSON转换为其他格式
    
    示例用法:
    1. 转CSV: convert_json input_data='[{"a":1},{"a":2}]' to_format=csv
    2. 转YAML: convert_json input_data='{"key":"value"}' to_format=yaml
    """
    try:
        if isinstance(input_data, str):
            data = json.loads(input_data)
        else:
            data = input_data
            
        if to_format == "csv":
            import csv
            import io
            output = io.StringIO()
            if isinstance(data, list):
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
            else:
                writer = csv.writer(output)
                for k, v in data.items():
                    writer.writerow([k, v])
            return {"success": True, "result": output.getvalue()}
            
        elif to_format == "yaml":
            import yaml
            return {"success": True, "result": yaml.dump(data)}
            
        elif to_format == "xml":
            from dicttoxml import dicttoxml
            return {"success": True, "result": dicttoxml(data).decode()}
            
        else:
            return {"success": False, "error": f"不支持的格式: {to_format}"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

def init_config():
    """初始化配置"""
    # 检查jq是否安装
    try:
        subprocess.run(["jq", "--version"], check=True, capture_output=True)
    except Exception:
        print("警告: jq工具未安装，部分功能可能受限")

if __name__ == "__main__":
    init_config()
    mcp.run()