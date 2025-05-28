import os
import subprocess
import json
import xml.etree.ElementTree as ET
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("单元测试工具")

def parse_gtest_output(output):
    """解析gtest输出"""
    try:
        result = {
            "tests": 0,
            "failures": 0,
            "disabled": 0,
            "errors": 0,
            "time": 0
        }
        # 简单解析gtest输出
        for line in output.split('\n'):
            if "[==========]" in line:
                if "tests from" in line:
                    result["tests"] = int(line.split()[2])
                elif "tests ran" in line:
                    parts = line.split()
                    result["failures"] = int(parts[parts.index("failures,")-1])
                    result["disabled"] = int(parts[parts.index("disabled,")-1])
                    result["errors"] = int(parts[parts.index("errors,")-1])
        return result
    except Exception as e:
        return {"error": str(e)}

def parse_pytest_output(output):
    """解析pytest输出"""
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"error": "Invalid pytest JSON output"}
    except Exception as e:
        return {"error": str(e)}

def parse_junit_xml(xml_file):
    """解析JUnit XML输出"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        return {
            "tests": int(root.attrib.get("tests", 0)),
            "failures": int(root.attrib.get("failures", 0)),
            "errors": int(root.attrib.get("errors", 0)),
            "skipped": int(root.attrib.get("skipped", 0))
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_gtest(test_binary: str) -> dict:
    """
    运行gtest测试并返回结果
    :param test_binary: gtest测试可执行文件路径
    :return: 测试结果(JSON格式)
    """
    if not os.path.exists(test_binary):
        return {"error": f"测试文件 {test_binary} 不存在"}
    
    try:
        result = subprocess.run([test_binary, "--gtest_output=json"], 
                              check=True, capture_output=True, text=True)
        return parse_gtest_output(result.stdout)
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stdout}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_pytest(test_dir: str) -> dict:
    """
    运行pytest测试并返回结果
    :param test_dir: pytest测试目录路径
    :return: 测试结果(JSON格式)
    """
    if not os.path.exists(test_dir):
        return {"error": f"测试目录 {test_dir} 不存在"}
    
    try:
        result = subprocess.run(
            ["pytest", test_dir, "--json-report"],
            check=True, capture_output=True, text=True
        )
        report_file = os.path.join(test_dir, ".report.json")
        if os.path.exists(report_file):
            with open(report_file) as f:
                return json.load(f)
        return parse_pytest_output(result.stdout)
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stdout}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_junit(test_command: str, xml_output: str) -> dict:
    """
    运行JUnit测试并返回结果
    :param test_command: 执行测试的命令
    :param xml_output: JUnit XML输出文件路径
    :return: 测试结果(JSON格式)
    """
    try:
        subprocess.run(test_command.split(), check=True)
        return parse_junit_xml(xml_output)
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.stdout}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    mcp.run()