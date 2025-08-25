from typing import Union, List, Dict
import platform
import os

import yaml
import datetime
import subprocess
from typing import Any, Dict
import psutil
import tempfile
from datetime import datetime
from mcp.server import FastMCP

# Create an MCP server
language = 'zh'


def init():
    """初始化函数"""
    global language
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        language = config.get("language", "zh")
    except Exception as e:
        print(f"load config.yaml error: {str(e)}")
        language = "en"


init()
mcp = FastMCP("Perf_Svg MCP Server", host="0.0.0.0", port=12141)


@mcp.prompt(name="self_introduction",
            description="工具定位")
def self_introduction() -> str:
    return "面向运维、开发人员，支持自然语言对接，实现指定应用进程火焰图生成，实现3个工具接口，分别为perf采集工具，perf安装工具，火焰图转换工具 "


def run_command(command, shell=True, check=True, capture_output=False, cwd=None,
                timeout=None, stdout=None, stderr=None):
    """执行系统命令并处理结果（增强版，支持超时和输出重定向）"""
    try:
        result = subprocess.run(
            command,
            shell=shell,
            check=check,
            capture_output=capture_output,
            text=True,
            cwd=cwd,
            timeout=timeout,
            stdout=stdout,
            stderr=stderr
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {command}")
        print(f"错误输出: {e.stderr}")
        raise e
    except subprocess.TimeoutExpired:
        print(f"命令执行超时: {command}")
        raise
    except Exception as e:
        print(f"命令执行异常: {command}, 错误: {str(e)}")
        raise e


@mcp.tool(
    name="使用top命令获取内存占用最多的k个进程"
    if language == "zh"
    else
    "top_collect_tool",
    description='''
    获取当前占用内存最多的k个进程
    1.输入k的值，默认为5，当然可以根据实际情况调整
    2.返回包含进程信息的字典列表，每个字典包含以下
    键:
        - pid: 进程ID
        - name: 进程名称
        - memory: 占用内存（单位：MB）
    '''
    if language == "zh"
    else
    '''
    Get the top k processes consuming the most memory.
    1. Input the value of k, default is 5， but can be adjusted based on actual needs.
    2. Returns a list of dictionaries containing process information, each dictionary includes the following keys
        - pid: Process ID
        - name: Process Name
        - memory: Memory Usage (in MB)
    '''

)
def top_collect_tool(k: int = 5) -> List[Dict[str, Any]]:
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            memory_usage = proc.info['memory_info'].rss / (1024 * 1024)  # 转换为MB
            processes.append({
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'memory': memory_usage
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 按内存使用量排序并取前k个
    processes.sort(key=lambda x: x['memory'], reverse=True)
    return processes[:k]


@mcp.tool(
    name="获取指定进程的详细信息"
    if language == "zh"
    else
    "get_process_info_tool",
    description="""
        获取指定进程的详细信息
        输入:
            pid: 进程ID（整数）
        输出:
            返回包含以下键的字典:
                - pid: 进程ID
                - name: 进程名称
                - status: 进程状态
                - create_time: 创建时间（时间戳）
                - cpu_times: CPU时间（用户时间和系统时间）
                - memory_info: 内存信息（RSS和VMS）
                - open_files: 打开的文件列表
                - connections: 网络连接信息（IP和端口）
        """
    if language == "zh"
    else
    """
        Get detailed information about a specified process.
        Input:
            pid: Process ID (integer)
        Output:
            Returns a dictionary containing the following keys:
                - pid: Process ID
                - name: Process Name
                - status: Process Status
                - create_time: Creation Time (timestamp)
                - cpu_times: CPU Times (user time and system time)
                - memory_info: Memory Information (RSS and VMS)
                - open_files: List of Open Files
                - connections: Network Connection Information (IP and Port)
        """

)
def get_process_info(pid: int) -> Dict[str, Any]:
    try:
        process = psutil.Process(pid)
        return {
            "pid": process.pid,
            "name": process.name(),
            "status": process.status(),
            "create_time": process.create_time(),
            "cpu_times": process.cpu_times(),
            "memory_info": process.memory_info(),
            "open_files": process.open_files(),
            "connections": process.connections()
        }
    except psutil.NoSuchProcess:
        return {"error": "Process not found"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(
    name=(
        "将进程名称转换为PID"
        if language == "zh"
        else
        "process_name_to_pid_tool"
    ),
    description=(
        """        将进程名称转换为PID
        输入:
            process_name: 进程名称（字符串）
        输出:
            返回包含以下字典的列表:
                - pid: 进程ID
                - name: 进程名称
        """
        if language == "zh"
        else
        """        Convert process name to PID.
        Input:
            process_name: Process Name (string)
        Output:
            Returns a list of dictionaries containing:
                - pid: Process ID
                - name: Process Name
        """
    )
)
def process_name_to_pid(process_name: str) -> List[Dict[str, Any]]:
    try:
        # 使用psutil获取所有进程信息
        processes = []
        for proc in psutil.process_iter(['pid', 'name']):
            if process_name.lower() in proc.info['name'].lower():
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name']
                })
        return processes if processes else [{"error": "No matching process found"}]
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool(
    name="perf_collect_tool"
    if language == "zh"
    else "perf_collect_tool",
    description="""
            使用perf工具采集指定进程的性能数据
            输入:
            pid: 目标进程的PID（整数）
            输出:
            返回采集结果的字符串，包含成功或失败的信息
        """
    if language == "zh"
    else
    """
            Use the perf tool to collect performance data for a specified process.
            Input:
            pid: Target process PID (integer)
            Output:
            Returns a string with the result of the collection, including success or failure information.
        """


)
def perf_collect_tool(pid: int) -> str:
    # 1. 解析目标进程PID

    # 2. 处理已存在的perf.data文件
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    perf_data_path = os.path.join(os.getcwd(), f"perf_{pid}_{current_time}.data")
    if os.path.exists(perf_data_path):
        try:
            os.remove(perf_data_path)
        except PermissionError:
            if language == "zh":
                return "错误: 没有权限删除已存在的perf.data文件"
            else:
                return "error: No permission to delete existing perf.data file"
        except Exception as e:
            if language == "zh":
                return f"错误: 删除perf.data时发生异常 - {str(e)}"
            else:
                return f"error: Exception occurred while deleting perf.data - {str(e)}"

    perf_cmd = [
        'perf', 'record',
        '-p', str(pid),
        '-o', perf_data_path,
        '-g',                # 记录调用栈
        '-e', 'cycles',      # 明确指定事件类型（CPU周期）
        '-- sleep 5'         # 让perf自动运行5秒后退出（更可靠）
    ]

    try:
        # 启动perf进程，使用shell=True执行带sleep的命令
        perf_process = subprocess.Popen(
            ' '.join(perf_cmd),  # 用字符串形式便于shell解析sleep
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # 等待perf自行结束（无需手动发信号）
        stdout, stderr = perf_process.communicate()
        returncode = perf_process.returncode

        # 检查结果
        if returncode == 0:
            if os.path.exists(perf_data_path) and os.path.getsize(perf_data_path) > 0:
                if language == "zh":
                    return f"成功: 已采集PID {pid} 的性能数据，保存至 {perf_data_path}（{os.path.getsize(perf_data_path)} 字节）"
                else:
                    return f"Success: Collected performance data for PID {pid}, saved to {perf_data_path} ({os.path.getsize(perf_data_path)} bytes)"
            else:
                if language == "zh":
                    return "警告: 命令执行成功，但未生成有效的perf.data文件"
                else:
                    return "Warning: Command executed successfully, but no valid perf.data file was generated"
        else:
            error_msg = stderr.strip()
            if not error_msg:
                if language == "zh":
                    error_msg = "未知错误"
                else:
                    error_msg = "Unknown error"
            if language == "zh":
                return f"错误: perf命令执行失败（返回码 {returncode}）- {error_msg}"
            else:
                return f"error: perf command failed (return code {returncode}) - {error_msg}"

    except subprocess.TimeoutExpired:
        # 超时情况下强制终止并清理
        perf_process.kill()
        if language == "zh":
            return "错误: perf采集超时"
        else:
            return "error: perf collection timed out"
    except Exception as e:
        if language == "zh":
            return f"错误: 采集过程异常 - {str(e)}"
        else:
            return f"error: Exception occurred during collection - {str(e)}"

    except subprocess.TimeoutExpired:
        # 若perf未响应终止信号，强制杀死
        perf_process.kill()
        if language == "zh":
            return "错误: 无法正常终止perf进程，请检查目标进程是否正常"
        else:
            return "error: Unable to terminate perf process normally, please check if the target process is running"
    except Exception as e:
        if language == "zh":
            return f"错误: 采集过程异常 - {str(e)}"
        else:
            return f"error: Exception occurred during collection - {str(e)}"


@mcp.tool(
    name="install_perf_tool"
    if language == "zh"
    else "install_perf_tool",
    description="""
        perf安装工具，使用yum安装perf工具，添加超时控制避免请求超时
        输入:
        timeout_seconds: 安装命令超时时间（默认300秒，可根据网络调整）
        输出:
        str: 返回安装结果字符串，包含成功或失败的信息
    """
    if language == "zh"
    else
    """
        Perf installation tool using yum, with timeout control to avoid request timeouts.
        Input:
        timeout_seconds: Timeout for the installation command (default 300 seconds, can be adjusted based on network conditions)
        Output:
        str: Returns a string with the installation result, including success or failure information
    """
)
def install_perf_tool(timeout_seconds: int = 300) -> str:
    try:
        # 执行yum安装（使用yum包管理器）
        install_cmd = ['sudo', 'yum', 'install', '-y', 'perf']

        # 执行安装（超时控制）
        install_result = run_command(
            install_cmd,
            shell=False,
            check=False,
            capture_output=True,
            timeout=timeout_seconds
        )

        if install_result.returncode == 0:
            if language == "zh":
                return "perf安装成功"
            else:
                return "Success: perf installed successfully"
        else:
            error_msg = install_result.stderr.strip()
            if not error_msg:
                if language == "zh":
                    error_msg = "未知错误"
                else:
                    error_msg = "Unknown error"
            if language == "zh":
                return f"安装失败（返回码：{install_result.returncode}）：{error_msg}"
            else:
                return f"Installation failed (return code: {install_result.returncode}): {error_msg}"

    except subprocess.TimeoutExpired:
        # 捕获超时异常，明确提示yum安装命令
        if language == "zh":
            return f"安装超时（超过{timeout_seconds}秒）。建议手动执行命令安装：\nsudo yum install -y perf"
        else:
            return f"Installation timed out (exceeded {timeout_seconds} seconds). It is recommended to manually execute the installation command:\nsudo yum install -y perf"
    except PermissionError:
        if language == "zh":
            return "权限不足，请用sudo运行脚本"
        else:
            return "error: Insufficient permissions, please run the script with sudo"
    except FileNotFoundError:
        if language == "zh":
            return "未找到yum或sudo命令，无法安装"
        else:
            return "error: Unable to find yum or sudo command, installation is not possible"
    except Exception as e:
        if language == "zh":
            return f"安装出错：{str(e)}"
        else:
            return f"error: Exception occurred during installation - {str(e)}"


@mcp.tool(
    name="火焰图转换工具"
    if language == "zh"
    else
    "generate_flamegraph_tool",
    description="""
        接收perf.data文件路径，使用FlameGraph工具生成火焰图
        输入:
        perf_data_path: perf.data文件路径（必须存在且非空）
        输出:
        Tuple[bool, Optional[str]]:
        - 成功时返回 (True, 火焰图SVG文件路径)
        - 失败时返回 (False, 错误信息)
        """
    if language == "zh"
    else
    """
        Accepts the path to a perf.data file and generates a flame graph using the FlameGraph tool.
        Input:
        perf_data_path: Path to the perf.data file (must exist and be non-empty)
        Output:
        str:
        Returns the path to the generated flame graph SVG file on success, or an error message on failure.
        """
)
def generate_flamegraph_tool(perf_data_path: str) -> str:
    # 定义需要的工具路径和仓库地址
    STACKCOLLAPSE_TOOL = "FlameGraph/stackcollapse-perf.pl"
    FLAMEGRAPH_TOOL = "FlameGraph/flamegraph.pl"
    FLAMEGRAPH_REPO = "https://githubfast.com/brendangregg/FlameGraph.git"
    # 在当前工作目录创建FlameGraph目录
    FLAMEGRAPH_DIR = os.path.join(os.getcwd(), "FlameGraph")

    # 第一步：检查并安装火焰图工具
    def check_tool(tool_name):
        """检查工具是否存在"""
        try:
            import os
            return os.path.exists(tool_name)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def install_flamegraph_tools():
        """安装FlameGraph工具集到当前目录的FlameGraph文件夹"""
        try:
            # 检查git是否安装
            try:
                run_command(
                    ["git", "--version"],
                    shell=False,
                    check=True,
                    capture_output=True,
                    timeout=10
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                return False

            # 清理已存在的目录（如果存在）
            if os.path.exists(FLAMEGRAPH_DIR):
                try:
                    import shutil
                    shutil.rmtree(FLAMEGRAPH_DIR)
                except Exception as e:
                    return False

            # 创建目录
            try:
                os.makedirs(FLAMEGRAPH_DIR, exist_ok=True)
            except PermissionError:
                return False
            except Exception as e:
                return False

            # 克隆仓库到指定目录
            clone_cmd = ["git", "clone", FLAMEGRAPH_REPO, FLAMEGRAPH_DIR]
            try:
                run_command(
                    clone_cmd,
                    shell=False,
                    check=True,
                    capture_output=True,
                    timeout=300
                )
            except subprocess.CalledProcessError as e:
                return False

            # 检查工具文件是否存在
            stackcollapse_path = os.path.join(FLAMEGRAPH_DIR, STACKCOLLAPSE_TOOL)
            flamegraph_path = os.path.join(FLAMEGRAPH_DIR, FLAMEGRAPH_TOOL)

            if not (os.path.exists(stackcollapse_path) and os.path.exists(flamegraph_path)):
                return False

            # 将工具路径添加到环境变量
            os.environ["PATH"] = f"{FLAMEGRAPH_DIR}:{os.environ['PATH']}"
            return True

        except Exception as e:
            return False

    # 检查工具是否存在，不存在则安装
    if not (check_tool(STACKCOLLAPSE_TOOL) and check_tool(FLAMEGRAPH_TOOL)):
        install_success, install_msg = install_flamegraph_tools()
        if not install_success:
            if language == "zh":
                return f"火焰图工具缺失，安装失败: {install_msg}"
            else:
                return f"flame graph tools are missing, installation failed: {install_msg}"

    # 定义文件路径
    file = os.path.basename(perf_data_path)
    file_name = os.path.splitext(file)[0]
    unfold_path = os.path.join(os.getcwd(), file_name+".unfold")
    svg_path = os.path.join(os.getcwd(), file_name+".svg")

    # 检查perf.data是否存在
    if not os.path.exists(perf_data_path):
        if language == "zh":
            return f"未找到perf.data文件，路径：{perf_data_path}"
        else:
            return f"perf.data file not found, path: {perf_data_path}"

    # 检查文件是否为空
    if os.path.getsize(perf_data_path) == 0:
        if language == "zh":
            return "perf.data文件为空"
        else:
            return "perf.data file is empty"

    folded_path = None  # 初始化临时折叠文件路径变量
    try:
        # 第一步：将perf.data解析为perf.unfold
        try:
            with open(unfold_path, 'w') as unfold_file:
                run_command(
                    ['perf', 'script', '-i', perf_data_path],
                    shell=False,
                    check=True,
                    capture_output=False,
                    stdout=unfold_file,
                    stderr=subprocess.PIPE
                )

            if not os.path.exists(unfold_path) or os.path.getsize(unfold_path) == 0:
                if language == "zh":
                    return "生成perf.unfold文件失败或文件为空"
                else:
                    return "error: Failed to generate perf.unfold file or file is empty"

        except subprocess.CalledProcessError as e:
            if language == "zh":
                error_msg = f"解析perf.data失败: {e.stderr.strip()}"
            else:
                error_msg = f"error: Failed to parse perf.data: {e.stderr.strip()}"
            return error_msg
        except Exception as e:
            if language == "zh":
                return f"生成perf.unfold时发生错误: {str(e)}"
            else:
                return f"error: Exception occurred while generating perf.unfold: {str(e)}"

        # 第二步：符号折叠处理
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.folded') as folded_file:
                folded_path = folded_file.name

                run_command(
                    [STACKCOLLAPSE_TOOL, unfold_path],
                    shell=False,
                    check=True,
                    capture_output=False,
                    stdout=folded_file,
                    stderr=subprocess.PIPE
                )

        except subprocess.CalledProcessError as e:
            if language == "zh":
                error_msg = f"符号折叠失败: {e.stderr.strip()}"
            else:
                error_msg = f"error: Failed to collapse symbols: {e.stderr.strip()}"
            return error_msg
        except FileNotFoundError:
            if language == "zh":
                return f"未找到{STACKCOLLAPSE_TOOL}工具，请手动检查FlameGraph目录"
            else:
                return f"error: {STACKCOLLAPSE_TOOL} tool not found, please manually check the FlameGraph directory"
        except Exception as e:
            if language == "zh":
                return f"符号折叠时发生错误: {str(e)}"
            else:
                return f"error: Exception occurred while collapsing symbols: {str(e)}"

        # 第三步：生成火焰图
        try:
            # 确保覆盖已有文件
            if os.path.exists(svg_path):
                os.remove(svg_path)

            with open(svg_path, 'w') as svg_file:
                run_command(
                    [FLAMEGRAPH_TOOL, folded_path],
                    shell=False,
                    check=True,
                    capture_output=False,
                    stdout=svg_file,
                    stderr=subprocess.PIPE
                )

            if not os.path.exists(svg_path) or os.path.getsize(svg_path) == 0:
                if language == "zh":
                    return "生成perf.svg文件失败或文件为空"
                else:
                    return "error: Failed to generate perf.svg file or file is empty"
            return os.path.abspath(svg_path)

        except subprocess.CalledProcessError as e:
            if language == "zh":
                error_msg = f"生成火焰图失败: {e.stderr.strip()}"
            else:
                error_msg = f"error: Failed to generate flame graph: {e.stderr.strip()}"
            return error_msg
        except FileNotFoundError:
            if language == "zh":
                return f"未找到{FLAMEGRAPH_TOOL}工具，请手动检查FlameGraph目录"
            else:
                return f"error: {FLAMEGRAPH_TOOL} tool not found, please manually check the FlameGraph directory"
        except Exception as e:
            if language == "zh":
                return f"生成火焰图时发生错误: {str(e)}"
            else:
                return f"error: Exception occurred while generating flame graph: {str(e)}"

    finally:
        # 清理临时折叠文件
        if folded_path and os.path.exists(folded_path):
            try:
                os.remove(folded_path)
            except Exception:
                pass  # 不处理清理失败，避免产生输出


@mcp.tool(
    name="获取当前系统时间"
    if language == "zh"
    else "get_current_time_tool",
    description="""
        获取当前系统时间
        输出:
            返回当前系统时间的字符串，格式为YYYY-MM-DD HH:MM:SS
        """
    if language == "zh"
    else
    """
        Get the current system time.
        Output:
            Returns a string with the current system time in the format YYYY-MM-DD HH:MM:SS
        """
)
def get_current_time() -> str:
    try:
        # 获取当前时间
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return current_time
    except Exception as e:
        if language == "zh":
            return f"错误: 获取当前时间时发生异常 - {str(e)}"
        else:
            return f"error: Exception occurred while getting current time - {str(e)}"


@mcp.tool(
    name="将文字写入文件"
    if language == "zh"
    else "write_text_to_file_tool",
    description="""
        将指定文字写入文件
        输入:
            text: 要写入的文字（字符串）
            file_name: 文件名（字符串），如果不存在则创建
        输出:
            返回写入结果的字符串，包含成功或失败的信息
        """
    if language == "zh"
    else
    """
        Write specified text to a file.
        Input:
            text: Text to write (string)
            file_name: File name (string), will be created if it does not exist
        Output:
            Returns a string with the result of the write operation, including success or failure information
        """
)
def write_text_to_file(text: str, file_name: str) -> str:
    try:
        # 检查file_name是否为None或空字符串
        if file_name is None:
            if language == "zh":
                return "错误: 文件名不能为None"
            else:
                return "error: File name cannot be None"

        if not isinstance(file_name, str):
            if language == "zh":
                return "错误: 文件名必须是字符串类型"
            else:
                return "error: File name must be a string"

        # 确保文件名不包含路径分隔符
        if os.path.sep in file_name or (os.path.altsep and os.path.altsep in file_name):
            if language == "zh":
                return "错误: 文件名不能包含路径分隔符"
            else:
                return "error: File name cannot contain path separators"

        # 写入文件
        file_path = os.path.join(os.getcwd(), file_name)
        with open(file_path, 'w', encoding='utf-8', errors="ignore") as f:
            f.write(text)

        if language == "zh":
            return f"成功: 已将文字写入文件 {file_path}"
        else:
            return f"Success: Text written to file {file_path}"

    except Exception as e:
        if language == "zh":
            return f"错误: 写入文件时发生异常 - {str(e)}"
        else:
            return f"error: Exception occurred while writing to file - {str(e)}"


@mcp.tool(
    name="获取当前机器的内存使用情况"
    if language == "zh"
    else "get_memory_usage_tool",
    description="""
        获取当前机器的内存使用情况
        输出:
            返回一个字典，包含以下键:
                - total: 总内存（单位：MB）
                - used: 已使用内存（单位：MB）
                - free: 可用内存（单位：MB）
                - percent: 内存使用百分比
        """
    if language == "zh"
    else
    """
        Get the current memory usage of the machine.
        Output:
            Returns a dictionary containing the following keys:
                - total: Total Memory (in MB)
                - used: Used Memory (in MB)
                - free: Free Memory (in MB)
                - percent: Memory Usage Percentage
        """
)
def get_memory_usage() -> Dict[str, Union[int, float]]:
    try:
        # 获取内存信息
        memory_info = psutil.virtual_memory()
        return {
            "total": memory_info.total // (1024 * 1024),  # 转换为MB
            "used": memory_info.used // (1024 * 1024),    # 转换为MB
            "free": memory_info.free // (1024 * 1024),    # 转换为MB
            "percent": memory_info.percent
        }
    except Exception as e:
        if language == "zh":
            return {"error": f"获取内存使用情况时发生异常 - {str(e)}"}
        else:
            return {"error": f"Exception occurred while getting memory usage - {str(e)}"}


@mcp.tool(
    name="获取当前机器的CPU使用情况"
    if language == "zh"
    else "get_cpu_usage_tool",
    description="""
        获取当前机器的CPU使用情况
        输出:
            返回一个字典，包含以下键:
                - cpu_count: CPU核心数
                - cpu_percent: CPU使用百分比
        """
    if language == "zh"
    else
    """
        Get the current CPU usage of the machine.
        Output:
            Returns a dictionary containing the following keys:
                - cpu_count: Number of CPU cores
                - cpu_percent: CPU Usage Percentage
        """
)
def get_cpu_usage() -> Dict[str, Union[int, float]]:
    try:
        # 获取CPU核心数
        cpu_count = psutil.cpu_count(logical=True)
        # 获取CPU使用百分比
        cpu_percent = psutil.cpu_percent(interval=1)
        return {
            "cpu_count": cpu_count,
            "cpu_percent": cpu_percent
        }
    except Exception as e:
        if language == "zh":
            return {"error": f"获取CPU使用情况时发生异常 - {str(e)}"}
        else:
            return {"error": f"Exception occurred while getting CPU usage - {str(e)}"}


@mcp.tool(
    name="获取当前机器的磁盘使用情况"
    if language == "zh"
    else "get_disk_usage_tool",
    description="""
        获取当前机器的磁盘使用情况
        输出:
            返回一个字典，包含以下键:
                - total: 总磁盘空间（单位：GB）
                - used: 已使用磁盘空间（单位：GB）
                - free: 可用磁盘空间（单位：GB）
                - percent: 磁盘使用百分比
        """
    if language == "zh"
    else
    """
        Get the current disk usage of the machine.
        Output:
            Returns a dictionary containing the following keys:
                - total: Total Disk Space (in GB)
                - used: Used Disk Space (in GB)
                - free: Free Disk Space (in GB)
                - percent: Disk Usage Percentage
        """
)
def get_disk_usage() -> Dict[str, Union[int, float]]:
    try:
        # 获取磁盘使用情况
        disk_usage = psutil.disk_usage('/')
        return {
            "total": disk_usage.total // (1024 * 1024 * 1024),  # 转换为GB
            "used": disk_usage.used // (1024 * 1024 * 1024),    # 转换为GB
            "free": disk_usage.free // (1024 * 1024 * 1024),    # 转换为GB
            "percent": disk_usage.percent
        }
    except Exception as e:
        if language == "zh":
            return {"error": f"获取磁盘使用情况时发生异常 - {str(e)}"}
        else:
            return {"error": f"Exception occurred while getting disk usage - {str(e)}"}


@mcp.tool(
    name="获取指定目录下的文件和目录的信息"
    if language == "zh"
    else "get_directory_files_info_tool",
    description="""
        获取指定目录下的文件和目录的信息
        输入:
            directory: 目录路径（字符串）
        输出:
            返回一个字典，包含以下键:
                - files: 文件信息列表，每个文件信息是一个字典，包含以下键:
                    - name: 文件名
                    - size: 文件大小（单位：字节）
                    - modified_time: 最后修改时间（时间戳）
                    - type: 文件类型（"file" 或 "directory"）
                - error: 错误信息（如果发生异常）
        """
    if language == "zh"
    else
    """
        Get information about files and directories in a specified directory.
        Input:
            directory: Directory path (string)
        Output:
            Returns a dictionary containing the following keys:
                - files: List of file information, each file info is a dictionary with the following keys:
                    - name: File name
                    - size: File size (in bytes)
                    - modified_time: Last modified time (timestamp)
                    - type: File type ("file" or "directory")
                - error: Error message (if an exception occurs)
        """
)
def get_directory_files_info(directory: str) -> Dict[str, Union[List[Dict[str, Any]], str]]:
    try:
        # 检查目录是否存在
        if not os.path.exists(directory):
            if language == "zh":
                return {"error": f"目录不存在: {directory}"}
            else:
                return {"error": f"Directory does not exist: {directory}"}

        # 获取目录下的文件和目录信息
        files_info = []
        for entry in os.scandir(directory):
            if entry.is_file():
                files_info.append({
                    "name": entry.name,
                    "size": entry.stat().st_size,
                    "modified_time": entry.stat().st_mtime,
                    "type": "file"
                })
            else:
                files_info.append({
                    "name": entry.name,
                    "size": 0,  # 目录大小通常不计算
                    "modified_time": entry.stat().st_mtime,
                    "type": "directory"
                })

        return {"files": files_info, "error": ""}
    except Exception as e:
        if language == "zh":
            return {"error": f"获取目录文件信息时发生异常 - {str(e)}"}
        else:
            return {"error": f"Exception occurred while getting directory files info - {str(e)}"}


@mcp.tool(
    name="获取当前操作系统信息"
    if language == "zh"
    else "get_system_info_tool",
    description="""
        获取当前操作系统信息
        输出:
            返回一个字典，包含以下键:
                - os_name: 操作系统名称
                - os_version: 操作系统版本
                - architecture: 系统架构
                - hostname: 主机名
        """
    if language == "zh"
    else
    """
        Get the current operating system information.
        Output:
            Returns a dictionary containing the following keys:
                - os_name: Operating System Name
                - os_version: Operating System Version
                - architecture: System Architecture
                - hostname: Hostname
        """
)
def get_system_info() -> Dict[str, str]:
    try:
        os_release_path = '/etc/openEuler-release'
        if os.path.exists(os_release_path):
            with open(os_release_path, 'r') as f:
                os_info = f.read().strip()
            os_name, os_version = os_info.split(' ', 1)
        else:
            if language == "zh":
                os_name = "未知操作系统"
                os_version = "未知版本"
            else:
                os_name = "Unknown Operating System"
                os_version = "Unknown Version"
        # 获取操作系统信息
        os_info = {
            "os_name": os_name,
            "os_version": os_version,
            "architecture": platform.architecture()[0],
            "hostname": platform.node()
        }
        return os_info
    except Exception as e:
        if language == "zh":
            return {"error": f"获取操作系统信息时发生异常 - {str(e)}"}
        else:
            return {"error": f"Exception occurred while getting system info - {str(e)}"}


@mcp.tool(
    name="获取当前机器cpu的详细信息"
    if language == "zh"
    else "get_cpu_details_tool",
    description="""
        通过lscpu命令获取当前机器cpu的详细信息
    """
    if language == "zh"
    else """
        Get detailed information about the current machine's CPU using the lscpu command.
    """
)
def get_cpu_details() -> Dict[str, Union[str, int]]:
    try:
        # 执行lscpu命令获取CPU信息
        result = run_command(['lscpu'], shell=False, check=True, capture_output=True)
        output = result.stdout.strip().split('\n')

        cpu_info = {}
        for line in output:
            if ':' in line:
                key, value = line.split(':', 1)
                cpu_info[key.strip()] = value.strip()

        return cpu_info
    except Exception as e:
        if language == "zh":
            return {"error": f"获取CPU详细信息时发生异常 - {str(e)}"}
        else:
            return {"error": f"Exception occurred while getting CPU details - {str(e)}"}


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='sse')
