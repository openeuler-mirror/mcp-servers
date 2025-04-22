import subprocess
import argparse
from typing import Optional, Dict
from mcp.server.fastmcp import FastMCP
from pydantic import Field

# 在mcp初始化前添加参数解析
parser = argparse.ArgumentParser()
args, _ = parser.parse_known_args()

mcp = FastMCP("鲲鹏DevKit工具是一款涵盖系统/应用迁移、亲和分析、编译调试和调优诊断等的工具集")

@mcp.tool()
def analysis_python(
    task: str = Field(default="hotspot", description="性能分析任务类型，如:hotspot"),
    duration: Optional[int] = Field(default=None, description="采集持续时间(秒)，最小值1"),
    interval: Optional[int] = Field(default=10, description="采样间隔(毫秒)，范围1-1000"),
    pid: Optional[int] = Field(default=None, description="目标进程ID，仅采样指定PID"),
    output: Optional[str] = Field(default=None, description="报告输出路径，默认当前目录"),
    threads: bool = Field(default=False, description="是否显示每个线程的堆栈信息"),
    native: bool = Field(default=False, description="是否显示C和Python的调用栈"),
    nolineno: bool = Field(default=False, description="是否不显示行号"),
    help: bool = Field(default=False, description="显示帮助信息")
) -> Dict:
    """执行Python性能分析任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'py-perf', 'hotspot', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}
        
        if task != "hotspot":
            return {"error": "目前仅支持hotspot任务类型"}
            
        cmd = ['devkit', 'py-perf', 'hotspot']
        
        if duration:
            if duration < 1:
                return {"error": "duration必须大于等于1"}
            cmd.extend(['--duration', str(duration)])
            
        if interval:
            if interval < 1 or interval > 1000:
                return {"error": "interval必须在1-1000毫秒之间"}
            cmd.extend(['--interval', str(interval)])
            
        if pid:
            cmd.extend(['--pid', str(pid)])
            
        if output:
            cmd.extend(['--output', output])
            
        if threads:
            cmd.append('--threads')
            
        if native:
            cmd.append('--native')
            
        if nolineno:
            cmd.append('--nolineno')
            
        result = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.STDOUT
        )
        
        return {
            "result": result,
            "command": " ".join(cmd),
            "output_file": output if output else "FlameGraph-*.html"
        }
        
    except subprocess.CalledProcessError as e:
        return {
            "error": e.output,
            "command": " ".join(cmd) if 'cmd' in locals() else None
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def analysis_java(
    task: str = Field(default="hotspot", description="Java性能分析任务类型，如:hotspot等"),
    pid: Optional[int] = Field(default=None, description="目标Java进程ID"),
    event: Optional[str] = Field(default="CPU", description="分析事件类型: CPU|ALLOC|CYCLES|CACHE_MISSES|LOCK"),
    duration: Optional[int] = Field(default=20, description="采集持续时间(秒)，最小值1，最大值300"),
    interval: Optional[int] = Field(default=10, description="采样间隔(毫秒)，范围1-1000"),
    output: Optional[str] = Field(default=None, description="火焰图报告输出路径"),
    help: bool = Field(default=False, description="显示帮助信息")
) -> Dict:
    """执行Java性能分析任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'java-perf', 'hotspot', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}
        
        if task != "hotspot":
            return {"error": "目前仅支持hotspot任务类型"}
            
        cmd = ['devkit', 'java-perf', 'hotspot']
        
        if not pid:
            return {
                "error": "必须指定Java进程PID(--pid)",
                "missing_params": ["pid"],
                "suggestions": ["1234"]  # 示例PID
            }
        cmd.extend(['--pid', str(pid)])
        
        if event:
            valid_events = ["CPU", "ALLOC", "CYCLES", "CACHE_MISSES", "LOCK"]
            if event not in valid_events:
                return {"error": f"无效的事件类型，必须是: {', '.join(valid_events)}"}
            cmd.extend(['--event', event])
            
        if duration:
            if duration < 1 or duration > 300:
                return {"error": "duration必须在1-300秒之间"}
            cmd.extend(['--duration', str(duration)])
            
        if interval:
            if interval < 1 or interval > 1000:
                return {"error": "interval必须在1-1000毫秒之间"}
            cmd.extend(['--interval', str(interval)])
            
        if output:
            cmd.extend(['--output', output])
            
        result = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.STDOUT
        )
        
        return {
            "result": result,
            "command": " ".join(cmd),
            "output_file": output if output else "FlameGraph-*.html"
        }
        
    except subprocess.CalledProcessError as e:
        return {
            "error": e.output,
            "command": " ".join(cmd) if 'cmd' in locals() else None
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def devkit_sys_mig(
    command: str = Field(default="stmt", description="收集信息的模式: stmt/sbom/mvn_analyse"),
    config: Optional[str] = Field(default=None, description="输入参数配置文件路径"),
    directory: Optional[str] = Field(default=None, description="输入扫描文件目录"),
    source: Optional[str] = Field(default=None, description="输入扫描文件目录(统计源码行数)"),
    template: Optional[str] = Field(default=None, description="输入台账扫描结果模板路径"),
    output: Optional[str] = Field(default=None, description="报告输出目录"),
    log_level: Optional[int] = Field(default=1, description="日志级别: 0/1/2/3"),
    db_config: Optional[str] = Field(default=None, description="数据库配置信息"),
    multi_node: Optional[str] = Field(default=None, description="远程扫描服务器的组名"),
    encipher: Optional[str] = Field(default=None, description="需要加密的文本"),
    version: bool = Field(default=False, description="展示程序版本信息"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行系统迁移分析任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'sys-mig', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}
        
        if version:
            result = subprocess.check_output(
                ['devkit', 'sys-mig', '--version'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"version": result}
            
        if encipher:
            result = subprocess.check_output(
                ['devkit', 'sys-mig', '--encipher', encipher],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"encipher": result}

        # 参数验证
        if command == "stmt":
            if not directory:
                return {
                    "error": "stmt模式需要指定扫描目录(--directory)",
                    "missing_params": ["directory"],
                    "suggestions": ["/path/to/scan/dir1 /path/to/scan/dir2"]
                }
        elif command == "sbom":
            if not directory and not source:
                return {
                    "error": "sbom模式需要指定扫描目录(--directory)或源码目录(--source)",
                    "missing_params": ["directory", "source"],
                    "suggestions": ["/path/to/scan/dir", "/path/to/source/code"]
                }
        elif command == "mvn_analyse":
            if not source:
                return {
                    "error": "mvn_analyse模式需要指定源码目录(--source)",
                    "missing_params": ["source"],
                    "suggestions": ["/path/to/maven/project"]
                }
            
        cmd = ['devkit', 'sys-mig', '--command', command]
        
        if config:
            cmd.extend(['--config', config])
        if directory:
            cmd.extend(['--directory', directory])
        if source:
            cmd.extend(['--source', source])
        if template:
            cmd.extend(['--template', template])
        if output:
            cmd.extend(['--output', output])
        if log_level is not None:
            cmd.extend(['--log-level', str(log_level)])
        if db_config:
            cmd.extend(['--db-config', db_config])
        if multi_node:
            cmd.extend(['--multi-node', multi_node])
            
        try:
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"result": result}
            
        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []
            
            if "missing required argument" in error_msg.lower():
                if "--directory" in error_msg:
                    missing_params.append("directory")
                    suggestions.append("/path/to/scan/dir")
                if "--source" in error_msg:
                    missing_params.append("source")
                    suggestions.append("/path/to/source/code")
                if "--config" in error_msg:
                    missing_params.append("config")
                    suggestions.append("/path/to/config/file")
                    
            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
            
    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_porting_src_mig(
    input_path: str = Field(..., description="待扫描源码的文件夹或压缩包所在路径"),
    cmd: Optional[str] = Field(default=None, description="源码的构建命令"),
    source_type: Optional[str] = Field(default="c,c++,asm", description="待扫描源码类型"),
    target_os: Optional[str] = Field(default=None, description="迁移的目标操作系统"),
    compiler: Optional[str] = Field(default=None, description="编译器版本"),
    fortran_compiler: Optional[str] = Field(default="flang2.5.0.1", description="fortran代码的编译器版本"),
    build_tool: Optional[str] = Field(default="make", description="构建工具"),
    output: Optional[str] = Field(default=None, description="扫描报告的存放路径"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
    log_level: Optional[int] = Field(default=1, description="日志级别"),
    report_type: Optional[str] = Field(default="all", description="扫描报告的格式"),
    ignore: Optional[str] = Field(default="/opt/ignore_rules.json", description="屏蔽扫描规则文件"),
    ignore_path: Optional[str] = Field(default=None, description="需要屏蔽扫描的源码文件或源码文件夹路径"),
    macro: Optional[str] = Field(default=None, description="自定义x86平台宏"),
    keep_going: Optional[bool] = Field(default=False, description="发现arm/arm64/aarch64关键字是否继续扫描"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行源码迁移分析任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'porting', 'src-mig', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not input_path:
            return {
                "error": "必须指定输入路径(--input-path)",
                "missing_params": ["input_path"],
                "suggestions": ["/path/to/source/dir"]
            }

        # 构建命令
        cmd_list = ['devkit', 'porting', 'src-mig', '--input-path', input_path]

        if cmd:
            cmd_list.extend(['--cmd', cmd])
        if source_type:
            cmd_list.extend(['--source-type', source_type])
        if target_os:
            cmd_list.extend(['--target-os', target_os])
        if compiler:
            cmd_list.extend(['--compiler', compiler])
        if fortran_compiler:
            cmd_list.extend(['--fortran-compiler', fortran_compiler])
        if build_tool:
            cmd_list.extend(['--build-tool', build_tool])
        if output:
            cmd_list.extend(['--output', output])
        if timeout:
            cmd_list.extend(['--set-timeout', str(timeout)])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if report_type:
            cmd_list.extend(['--report-type', report_type])
        if ignore:
            cmd_list.extend(['--ignore', ignore])
        if ignore_path:
            cmd_list.extend(['--ignore-path', ignore_path])
        if macro:
            cmd_list.extend(['--macro', macro])
        if keep_going:
            cmd_list.extend(['--keep-going', str(keep_going)])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果
        return {
            "result": result,
            "report_paths": {
                "json": f"{output}/src-mig_*.json" if output else None,
                "csv": f"{output}/src-mig_*.csv" if output else None,
                "html": f"{output}/src-mig_*.html" if output else None
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--input-path" in error_msg:
                missing_params.append("input_path")
                suggestions.append("/path/to/source/dir")
            if "--cmd" in error_msg and "c/c++/asm/fortran/go" in error_msg:
                missing_params.append("cmd")
                suggestions.append("make")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_porting_pkg_mig(
    input_path: str = Field(..., description="待扫描软件包的文件夹或软件包路径，多个路径用空格分隔"),
    target_os: Optional[str] = Field(default=None, description="迁移的目标操作系统，默认为当前系统"),
    output: Optional[str] = Field(default=None, description="扫描报告的存放路径"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
    log_level: Optional[int] = Field(default=1, description="日志级别: 0/1/2/3"),
    report_type: Optional[str] = Field(default="all", description="扫描报告格式: all/json/html/csv"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行软件包迁移分析任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'porting', 'pkg-mig', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not input_path:
            return {
                "error": "必须指定输入路径(--input-path)",
                "missing_params": ["input_path"],
                "suggestions": ["/path/to/package1.rpm /path/to/package2.deb"]
            }

        # 构建命令
        cmd_list = ['devkit', 'porting', 'pkg-mig', '--input', input_path]

        if target_os:
            cmd_list.extend(['--target-os', target_os])
        if output:
            cmd_list.extend(['--output', output])
        if timeout:
            cmd_list.extend(['--set-timeout', str(timeout)])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if report_type:
            cmd_list.extend(['--report-type', report_type])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果
        return {
            "result": result,
            "report_paths": {
                "json": f"{output}/pkg-mig_*.json" if output else None,
                "csv": f"{output}/pkg-mig_*.csv" if output else None,
                "html": f"{output}/pkg-mig_*.html" if output else None
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--input" in error_msg:
                missing_params.append("input_path")
                suggestions.append("/path/to/package.rpm")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_advisor_run_mode(
    input_path: str = Field(..., description="待扫描的源码文件夹路径"),
    command: str = Field(..., description="源码构建命令。在服务器中正常执行的构建命令，若存在多个构建命令需使用英文分号分割并用英文单/双引号包住"),
    output_path: Optional[str] = Field(default=None, description="扫描报告的存放路径，默认存放在当前执行路径下"),
    log_level: Optional[int] = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
    report_type: Optional[str] = Field(default="all", description="扫描报告格式: all/json/html/csv"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行64位运行模式检查任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'advisor', 'run-mode', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not input_path:
            return {
                "error": "必须指定输入路径(--input)",
                "missing_params": ["input_path"],
                "suggestions": ["/path/to/source/dir"]
            }
        if not command:
            return {
                "error": "必须指定构建命令(--command)",
                "missing_params": ["command"],
                "suggestions": ["make", "\"mkdir build;cd build;cmake ..;make\""]
            }

        # 构建命令
        cmd_list = ['devkit', 'advisor', 'run-mode', '--input', input_path, '--command', command]

        if output_path:
            cmd_list.extend(['--output', output_path])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if report_type:
            cmd_list.extend(['--report-type', report_type])
        if timeout:
            cmd_list.extend(['--set-timeout', str(timeout)])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果
        return {
            "result": result,
            "report_paths": {
                "json": f"{output_path}/mode_check_*.json" if output_path else None,
                "csv": f"{output_path}/mode_check_*.csv" if output_path else None,
                "html": f"{output_path}/mode_check_*.html" if output_path else None
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--input" in error_msg:
                missing_params.append("input_path")
                suggestions.append("/path/to/source/dir")
            if "--command" in error_msg:
                missing_params.append("command")
                suggestions.append("make")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_advisor_addr_align(
    input_path: str = Field(..., description="待扫描的源码文件夹路径"),
    command: str = Field(..., description="源码构建命令。在服务器中正常执行的构建命令，若存在多个构建命令需使用英文分号分割并用英文单/双引号包住"),
    output_path: Optional[str] = Field(default=None, description="扫描报告的存放路径，默认存放在当前执行路径下"),
    report_type: Optional[str] = Field(default="all", description="扫描报告格式: all/json/html/csv"),
    log_level: Optional[int] = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行字节对齐检查任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'advisor', 'addr-align', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not input_path:
            return {
                "error": "必须指定输入路径(--input)",
                "missing_params": ["input_path"],
                "suggestions": ["/path/to/source/dir"]
            }
        if not command:
            return {
                "error": "必须指定构建命令(--command)",
                "missing_params": ["command"],
                "suggestions": ["make", "\"mkdir build;cd build;cmake ..;make\""]
            }

        # 构建命令
        cmd_list = ['devkit', 'advisor', 'addr-align', '--input', input_path, '--command', command]

        if output_path:
            cmd_list.extend(['--output', output_path])
        if report_type:
            cmd_list.extend(['--report-type', report_type])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if timeout:
            cmd_list.extend(['--set-timeout', str(timeout)])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果
        return {
            "result": result,
            "report_paths": {
                "json": f"{output_path}/addr-align_*.json" if output_path else None,
                "csv": f"{output_path}/addr-align_*.csv" if output_path else None,
                "html": f"{output_path}/addr-align_*.html" if output_path else None
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--input" in error_msg:
                missing_params.append("input_path")
                suggestions.append("/path/to/source/dir")
            if "--command" in error_msg:
                missing_params.append("command")
                suggestions.append("make")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_advisor_bc_gen(
    command: str = Field(..., description="源码构建命令。在服务器中正常执行的构建命令，若存在多个构建命令需使用英文分号分割并用英文单/双引号包住"),
    output_path: Optional[str] = Field(default=None, description="生成BC文件的存放路径，需要有写权限。默认存放在当前路径下，名称默认为'模块名称_时间戳'"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间，单位为分钟，若执行时间超过超时时间则退出执行"),
    log_level: Optional[int] = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
    threads: Optional[int] = Field(default=None, description="编译BC文件的线程数，默认线程数为当前环境CPU总数的一半"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """生成BC文件"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'advisor', 'bc-gen', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not command:
            return {
                "error": "必须指定构建命令(--command)",
                "missing_params": ["command"],
                "suggestions": ["make", "\"mkdir build;cd build;cmake ..;make\""]
            }

        # 构建命令
        cmd_list = ['devkit', 'advisor', 'bc-gen', '--command', command]

        if output_path:
            cmd_list.extend(['--output', output_path])
        if timeout is not None:
            cmd_list.extend(['--set-timeout', str(timeout)])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if threads is not None:
            cmd_list.extend(['--threads', str(threads)])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果中的BC文件路径
        bc_paths = {
            "linked_bc": None,
            "object_bc": None,
            "log_path": None
        }
        
        if "Output path of linked bc files" in result:
            bc_paths["linked_bc"] = result.split("Output path of linked bc files:")[1].split("\n")[0].strip()
        if "Output path of object bc files" in result:
            bc_paths["object_bc"] = result.split("Output path of object bc files:")[1].split("\n")[0].strip()
        if "Log path" in result:
            bc_paths["log_path"] = result.split("Log path:")[1].split("\n")[0].strip()

        return {
            "result": result,
            "bc_paths": bc_paths,
            "summary": {
                "linked_bc_count": int(result.split("there are ")[1].split(" linked bc files")[0]) if "linked bc files" in result else 0,
                "object_bc_count": int(result.split("and ")[1].split(" object bc files")[0]) if "object bc files" in result else 0,
                "failed_count": int(result.split("There are ")[1].split(" linked bc files fail")[0]) if "linked bc files fail" in result else 0
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--command" in error_msg:
                missing_params.append("command")
                suggestions.append("make")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_advisor_mm_check(
    input_path: str = Field(..., description="BC文件对应的源码文件夹路径"),
    bc_path: str = Field(..., description="BC文件夹路径，该路径下必须存在BC文件"),
    autofix: bool = Field(default=False, description="是否生成编译器配置文件"),
    autofix_dir: Optional[str] = Field(default=None, description="编译器配置文件的存放地址"),
    output_path: Optional[str] = Field(default=None, description="扫描报告的存放路径"),
    report_type: str = Field(default="all", description="扫描报告格式: all/json/html/csv"),
    log_level: int = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行静态内存一致性检查任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'advisor', 'mm-check', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not input_path:
            return {
                "error": "必须指定源码路径(--input)",
                "missing_params": ["input_path"],
                "suggestions": ["/path/to/source/dir"]
            }
        if not bc_path:
            return {
                "error": "必须指定BC文件路径(--bc-file)",
                "missing_params": ["bc_path"],
                "suggestions": ["/path/to/bc/files"]
            }
        if autofix_dir and not autofix:
            return {
                "error": "--autofix-dir需要--autofix=true才能生效",
                "missing_params": ["autofix"],
                "suggestions": ["--autofix true"]
            }

        # 构建命令
        cmd_list = ['devkit', 'advisor', 'mm-check', '--input', input_path, '--bc-file', bc_path]

        if autofix:
            cmd_list.extend(['--autofix', 'true'])
            if autofix_dir:
                cmd_list.extend(['--autofix-dir', autofix_dir])
        if output_path:
            cmd_list.extend(['--output', output_path])
        if report_type:
            cmd_list.extend(['--report-type', report_type])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if timeout is not None:
            cmd_list.extend(['--set-timeout', str(timeout)])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果中的报告路径
        report_paths = {}
        if "For the details information, please check:" in result:
            report_lines = result.split("For the details information, please check:")[1].strip().split("\n")
            for line in report_lines:
                if ".json" in line:
                    report_paths["json"] = line.strip()
                elif ".html" in line:
                    report_paths["html"] = line.strip()
                elif ".csv" in line:
                    report_paths["csv"] = line.strip()

        # 解析扫描摘要
        summary = {}
        if "Scanned" in result and "bc files" in result and "recommended modifications" in result:
            summary["bc_files_count"] = int(result.split("Scanned ")[1].split(" bc files")[0])
            summary["recommendations_count"] = int(result.split("there are ")[1].split(" recommended modifications")[0])

        return {
            "result": result,
            "report_paths": report_paths if report_paths else None,
            "summary": summary if summary else None,
            "configuration": {
                "input_path": input_path,
                "bc_path": bc_path,
                "autofix": autofix,
                "autofix_dir": autofix_dir,
                "output_path": output_path,
                "report_type": report_type,
                "log_level": log_level,
                "timeout": timeout
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--input" in error_msg:
                missing_params.append("input_path")
                suggestions.append("/path/to/source/dir")
            if "--bc-file" in error_msg:
                missing_params.append("bc_path")
                suggestions.append("/path/to/bc/files")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

@mcp.tool()
def devkit_advisor_matrix_check(
    input_path: str = Field(..., description="待扫描的源码文件夹路径"),
    optimization: str = Field(..., description="矩阵化优化方法: sme/domain"),
    command: Optional[str] = Field(default=None, description="源码构建命令。多个命令用分号分隔并用引号包住"),
    compile_command_json: Optional[str] = Field(default=None, description="compile_commands.json文件路径"),
    scan_dir: Optional[str] = Field(default=None, description="待扫描的源码文件夹或包路径，支持多路径"),
    build_tool: Optional[str] = Field(default="make", description="构建工具: make/cmake"),
    output_path: Optional[str] = Field(default=None, description="扫描报告存放路径"),
    report_type: str = Field(default="all", description="报告格式: all/json/html/csv"),
    log_level: int = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
    module: Optional[str] = Field(default=None, description="领域优化方法: compute/memory_access/communication"),
    timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
    help: bool = Field(default=False, description="获取帮助信息")
) -> Dict:
    """执行矩阵化检查任务"""
    try:
        if help:
            result = subprocess.check_output(
                ['devkit', 'advisor', 'matrix-check', '--help'],
                text=True,
                stderr=subprocess.STDOUT
            )
            return {"help": result}

        # 参数验证
        if not input_path:
            return {
                "error": "必须指定输入路径(--input)",
                "missing_params": ["input_path"],
                "suggestions": ["/path/to/source/dir"]
            }
        if not optimization:
            return {
                "error": "必须指定优化方法(--optimization)",
                "missing_params": ["optimization"],
                "suggestions": ["sme", "domain"]
            }
        if not command and not compile_command_json:
            return {
                "error": "必须指定构建命令(--command)或compile_commands.json(--compile-command-json)",
                "missing_params": ["command", "compile_command_json"],
                "suggestions": ["make", "/path/to/compile_commands.json"]
            }
        if optimization == "domain" and not module:
            return {
                "error": "当优化方法为domain时必须指定模块(--module)",
                "missing_params": ["module"],
                "suggestions": ["compute", "memory_access", "communication"]
            }

        # 构建命令
        cmd_list = ['devkit', 'advisor', 'matrix-check', '--input', input_path, '--optimization', optimization]

        if command:
            cmd_list.extend(['--command', command])
        if compile_command_json:
            cmd_list.extend(['--compile-command-json', compile_command_json])
        if scan_dir:
            cmd_list.extend(['--scan-dir', scan_dir])
        if build_tool:
            cmd_list.extend(['--build-tool', build_tool])
        if output_path:
            cmd_list.extend(['--output', output_path])
        if report_type:
            cmd_list.extend(['--report-type', report_type])
        if log_level is not None:
            cmd_list.extend(['--log-level', str(log_level)])
        if module:
            cmd_list.extend(['--module', module])
        if timeout is not None:
            cmd_list.extend(['--set-timeout', str(timeout)])

        # 执行命令
        result = subprocess.check_output(
            cmd_list,
            text=True,
            stderr=subprocess.STDOUT
        )

        # 解析结果中的报告路径
        report_paths = {}
        if "For the details information, please check:" in result:
            report_lines = result.split("For the details information, please check:")[1].strip().split("\n")
            for line in report_lines:
                if ".json" in line:
                    report_paths["json"] = line.strip()
                elif ".html" in line:
                    report_paths["html"] = line.strip()
                elif ".csv" in line:
                    report_paths["csv"] = line.strip()

        # 解析扫描摘要
        summary = {}
        if "Scanned" in result and "files" in result and "suggestions" in result:
            summary["files_count"] = int(result.split("Scanned ")[1].split(" files")[0])
            summary["suggestions_count"] = int(result.split("there are ")[1].split(" suggestions")[0])

        return {
            "result": result,
            "report_paths": report_paths if report_paths else None,
            "summary": summary if summary else None,
            "configuration": {
                "input_path": input_path,
                "optimization": optimization,
                "command": command,
                "compile_command_json": compile_command_json,
                "scan_dir": scan_dir,
                "build_tool": build_tool,
                "output_path": output_path,
                "report_type": report_type,
                "log_level": log_level,
                "module": module,
                "timeout": timeout
            }
        }

    except subprocess.CalledProcessError as e:
        error_msg = e.output
        missing_params = []
        suggestions = []

        if "missing required argument" in error_msg.lower():
            if "--input" in error_msg:
                missing_params.append("input_path")
                suggestions.append("/path/to/source/dir")
            if "--optimization" in error_msg:
                missing_params.append("optimization")
                suggestions.append("sme")
            if "--command" in error_msg and "--compile-command-json" not in error_msg:
                missing_params.append("command")
                suggestions.append("make")
            if "--compile-command-json" in error_msg and "--command" not in error_msg:
                missing_params.append("compile_command_json")
                suggestions.append("/path/to/compile_commands.json")
            if "--module" in error_msg and "domain" in error_msg:
                missing_params.append("module")
                suggestions.append("compute")

        return {
            "error": error_msg,
            "missing_params": missing_params if missing_params else None,
            "suggestions": suggestions if suggestions else None,
            "retry": bool(missing_params)
        }

    except Exception as e:
        return {
            "error": str(e),
            "retry": False
        }

if __name__ == "__main__":
    @mcp.tool()
    def devkit_advisor_vec_check(
        input_path: str = Field(..., description="BC文件对应的源码文件夹路径"),
        bc_path: str = Field(..., description="BC文件夹路径，该路径下必须存在BC文件"),
        command: str = Field(..., description="源码构建命令。在服务器中正常执行的构建命令，若存在多个构建命令需使用英文分号分割并用英文单/双引号包住"),
        compiler: str = Field(default="clang", description="指定用于编译源码的编译器: clang/gcc"),
        output_path: Optional[str] = Field(default=None, description="扫描报告的存放路径，默认存放在当前执行路径下"),
        report_type: str = Field(default="all", description="扫描报告格式: all/json/html/csv"),
        log_level: int = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
        timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
        sve_enable: bool = Field(default=False, description="是否启用SVE(ARM可变长度向量化指令)"),
        help: bool = Field(default=False, description="获取帮助信息")
    ) -> Dict:
        """执行向量化检查任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'advisor', 'vec-check', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not input_path:
                return {
                    "error": "必须指定源码路径(--input)",
                    "missing_params": ["input_path"],
                    "suggestions": ["/path/to/source/dir"]
                }
            if not bc_path:
                return {
                    "error": "必须指定BC文件路径(--bc-file)",
                    "missing_params": ["bc_path"],
                    "suggestions": ["/path/to/bc/files"]
                }
            if not command:
                return {
                    "error": "必须指定构建命令(--command)",
                    "missing_params": ["command"],
                    "suggestions": ["make", "\"mkdir build;cd build;cmake ..;make\""]
                }

            # 构建命令
            cmd_list = [
                'devkit', 'advisor', 'vec-check',
                '--input', input_path,
                '--bc-file', bc_path,
                '--command', command,
                '--compiler', compiler,
                '--report-type', report_type,
                '--log-level', str(log_level)
            ]

            if output_path:
                cmd_list.extend(['--output', output_path])
            if timeout is not None:
                cmd_list.extend(['--set-timeout', str(timeout)])
            if sve_enable:
                cmd_list.extend(['--sve-enable', 'true'])

            # 执行命令
            result = subprocess.check_output(
                cmd_list,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果中的报告路径
            report_paths = {}
            if "For the details information, please check:" in result:
                report_lines = result.split("For the details information, please check:")[1].strip().split("\n")
                for line in report_lines:
                    if ".json" in line:
                        report_paths["json"] = line.strip()
                    elif ".html" in line:
                        report_paths["html"] = line.strip()
                    elif ".csv" in line:
                        report_paths["csv"] = line.strip()

            # 解析扫描摘要
            summary = {}
            if "Scanned" in result and "bc files" in result and "recommended modifications" in result:
                summary["bc_files_count"] = int(result.split("Scanned ")[1].split(" bc files")[0])
                summary["recommendations_count"] = int(result.split("there are ")[1].split(" recommended modifications")[0])

            return {
                "result": result,
                "report_paths": report_paths if report_paths else None,
                "summary": summary if summary else None,
                "configuration": {
                    "input_path": input_path,
                    "bc_path": bc_path,
                    "command": command,
                    "compiler": compiler,
                    "output_path": output_path,
                    "report_type": report_type,
                    "log_level": log_level,
                    "timeout": timeout,
                    "sve_enable": sve_enable
                }
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--input" in error_msg:
                    missing_params.append("input_path")
                    suggestions.append("/path/to/source/dir")
                if "--bc-file" in error_msg:
                    missing_params.append("bc_path")
                    suggestions.append("/path/to/bc/files")
                if "--command" in error_msg:
                    missing_params.append("command")
                    suggestions.append("make")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }

        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def devkit_advisor_cacheline(
        input_path: str = Field(..., description="待扫描的源码文件夹路径"),
        output_path: Optional[str] = Field(default=None, description="扫描报告的存放路径，默认存放在当前执行路径下"),
        report_type: str = Field(default="all", description="扫描报告格式: all/json/html/csv"),
        log_level: int = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
        timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
        help: bool = Field(default=False, description="获取帮助信息")
    ) -> Dict:
        """执行缓存行对齐检查任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'advisor', 'cacheline', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not input_path:
                return {
                    "error": "必须指定输入路径(--input)",
                    "missing_params": ["input_path"],
                    "suggestions": ["/path/to/source/dir"]
                }

            # 构建命令
            cmd_list = ['devkit', 'advisor', 'cacheline', '--input', input_path]

            if output_path:
                cmd_list.extend(['--output', output_path])
            if report_type:
                cmd_list.extend(['--report-type', report_type])
            if log_level is not None:
                cmd_list.extend(['--log-level', str(log_level)])
            if timeout is not None:
                cmd_list.extend(['--set-timeout', str(timeout)])

            # 执行命令
            result = subprocess.check_output(
                cmd_list,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果中的报告路径
            report_paths = {}
            if "For the details information, please check:" in result:
                report_lines = result.split("For the details information, please check:")[1].strip().split("\n")
                for line in report_lines:
                    if ".json" in line:
                        report_paths["json"] = line.strip()
                    elif ".html" in line:
                        report_paths["html"] = line.strip()
                    elif ".csv" in line:
                        report_paths["csv"] = line.strip()

            # 解析扫描摘要
            summary = {}
            if "Scanned" in result and "files" in result and "recommended modifications" in result:
                summary["files_count"] = int(result.split("Scanned ")[1].split(" files")[0])
                summary["recommendations_count"] = int(result.split("there are ")[1].split(" recommended modifications")[0])

            return {
                "result": result,
                "report_paths": report_paths if report_paths else None,
                "summary": summary if summary else None,
                "configuration": {
                    "input_path": input_path,
                    "output_path": output_path,
                    "report_type": report_type,
                    "log_level": log_level,
                    "timeout": timeout
                }
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--input" in error_msg:
                    missing_params.append("input_path")
                    suggestions.append("/path/to/source/dir")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }

        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def devkit_advisor_affi_check(
        input_path: str = Field(..., description="待扫描的源码文件夹路径"),
        command: str = Field(..., description="源码构建命令。在服务器中正常执行的构建命令，若存在多个构建命令需使用英文分号分割并用英文单/双引号包住"),
        output_path: Optional[str] = Field(default=None, description="扫描报告的存放路径，默认存放在当前执行路径下"),
        report_type: str = Field(default="all", description="扫描报告格式: all/json/html/csv"),
        log_level: int = Field(default=1, description="日志级别: 0/1/2/3 (DEBUG/INFO/WARNING/ERROR)"),
        timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
        help: bool = Field(default=False, description="获取帮助信息")
    ) -> Dict:
        """执行构建亲和性检查任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'advisor', 'affi-check', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not input_path:
                return {
                    "error": "必须指定输入路径(--input)",
                    "missing_params": ["input_path"],
                    "suggestions": ["/path/to/source/dir"]
                }
            if not command:
                return {
                    "error": "必须指定构建命令(--command)",
                    "missing_params": ["command"],
                    "suggestions": ["make", "\"mkdir build;cd build;cmake ..;make\""]
                }

            # 构建命令
            cmd_list = ['devkit', 'advisor', 'affi-check', '--input', input_path, '--command', command]

            if output_path:
                cmd_list.extend(['--output', output_path])
            if report_type:
                cmd_list.extend(['--report-type', report_type])
            if log_level is not None:
                cmd_list.extend(['--log-level', str(log_level)])
            if timeout is not None:
                cmd_list.extend(['--set-timeout', str(timeout)])

            # 执行命令
            result = subprocess.check_output(
                cmd_list,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果中的报告路径
            report_paths = {}
            if "For the detailed information, please check:" in result:
                report_lines = result.split("For the detailed information, please check:")[1].strip().split("\n")
                for line in report_lines:
                    if ".json" in line:
                        report_paths["json"] = line.strip()
                    elif ".html" in line:
                        report_paths["html"] = line.strip()
                    elif ".csv" in line:
                        report_paths["csv"] = line.strip()

            # 解析扫描摘要
            summary = {}
            if "Scanned time:" in result:
                summary["scan_time"] = result.split("Scanned time:")[1].split("\n")[0].strip()
            if "Scan status:" in result:
                summary["status"] = result.split("Scan status:")[1].split("\n")[0].strip()
            if "dependency files can be accelerated" in result:
                summary["accelerated_files"] = int(result.split("dependency files can be accelerated")[0].split()[-1])

            return {
                "result": result,
                "report_paths": report_paths if report_paths else None,
                "summary": summary if summary else None,
                "configuration": {
                    "input_path": input_path,
                    "command": command,
                    "output_path": output_path,
                    "report_type": report_type,
                    "log_level": log_level,
                    "timeout": timeout
                }
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--input" in error_msg:
                    missing_params.append("input_path")
                    suggestions.append("/path/to/source/dir")
                if "--command" in error_msg:
                    missing_params.append("command")
                    suggestions.append("make")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }

        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def doctor_memoob(
        help: bool = Field(default=False, description="获取帮助信息"),
        log_level: int = Field(default=2, description="日志级别: 0(DEBUG)/1(INFO)/2(WARNING)/3(ERROR)"),
        package: bool = Field(default=False, description="是否将数据导入数据库并生成压缩包"),
        ns: bool = Field(default=False, description="应用程序异常后是否终止分析"),
        output: Optional[str] = Field(default=None, description="报告输出路径，默认为当前目录"),
        workload: str = Field(..., description="待分析应用的绝对路径")
    ) -> Dict:
        """执行内存覆盖分析任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'doctor', 'memoob', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not workload:
                return {
                    "error": "必须指定待分析应用路径",
                    "missing_params": ["workload"],
                    "suggestions": ["/path/to/application"]
                }

            # 构建命令
            cmd = ['devkit', 'doctor', 'memoob']
            
            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])
            if package:
                cmd.append('--package')
            if ns:
                cmd.append('--ns')
            if output:
                cmd.extend(['--output', output])
            cmd.append(workload)

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果
            report_path = None
            if output:
                report_path = f"{output}.tar" if package else output
            
            return {
                "result": result,
                "command": " ".join(cmd),
                "report_path": report_path
            }

        except subprocess.CalledProcessError as e:
            return {
                "error": e.output,
                "command": " ".join(cmd) if 'cmd' in locals() else None
            }
        except Exception as e:
            return {"error": str(e)}


    @mcp.tool()
    def devkit_doctor_crypt_scan(
        directory: str = Field(..., description="输入扫描目录路径", alias="d"),
        output: Optional[str] = Field(default=None, description="报告输出路径", alias="o"),
        help: bool = Field(default=False, description="获取帮助信息", alias="h")
    ) -> Dict:
        """执行密码算法扫描任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'doctor', 'crypt-scan', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not directory:
                return {
                    "error": "必须指定扫描目录(--directory)",
                    "missing_params": ["directory"],
                    "suggestions": ["/path/to/scan/dir"]
                }

            # 构建命令
            cmd = ['devkit', 'doctor', 'crypt-scan', '--directory', directory]
            
            if output:
                cmd.extend(['--output', output])

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            return {
                "result": result,
                "command": " ".join(cmd),
                "report_path": output if output else "CryptScanReport-*.html"
            }
            
        except subprocess.CalledProcessError as e:
            return {
                "error": e.output,
                "command": " ".join(cmd) if 'cmd' in locals() else None
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def devkit_doctor_sen_scan(
        input_path: str = Field(..., description="输入扫描路径", alias="i"),
        output_path: Optional[str] = Field(default=None, description="报告输出路径", alias="o"),
        show: bool = Field(default=False, description="显示扫描结果", alias="S"),
        template_path: Optional[str] = Field(default=None, description="模板文件路径", alias="t"),
        sen_nums: Optional[list[str]] = Field(default=None, description="敏感信息编号列表(1/2/3/a/b/c)", alias="sn"),
        sen_file: Optional[str] = Field(default=None, description="敏感信息文件路径", alias="sf"),
        help: bool = Field(default=False, description="获取帮助信息", alias="h")
    ) -> Dict:
        """执行敏感信息扫描任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'doctor', 'sen-scan', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not input_path:
                return {
                    "error": "必须指定输入路径(--input)",
                    "missing_params": ["input_path"],
                    "suggestions": ["/path/to/scan/dir"]
                }

            # 构建命令
            cmd = ['devkit', 'doctor', 'sen-scan', '--input', input_path]

            if output_path:
                cmd.extend(['--output', output_path])
            if show:
                cmd.append('--show')
            if template_path:
                cmd.extend(['--template', template_path])
            if sen_nums:
                cmd.extend(['--sen-num', ",".join(sen_nums)])
            if sen_file:
                cmd.extend(['--sen-file', sen_file])

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果
            report_path = None
            if output_path:
                report_path = output_path
            elif "Scan report generated at:" in result:
                report_path = result.split("Scan report generated at:")[1].strip()

            return {
                "result": result,
                "command": " ".join(cmd),
                "report_path": report_path,
                "show_result": show
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--input" in error_msg:
                    missing_params.append("input_path")
                    suggestions.append("/path/to/scan/dir")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def devkit_debugger(
        type: str = Field(..., description="调试的启动方式，仅支持以Launch方式调试程序", alias="t"),
        workload: str = Field(..., description="待调试程序可执行文件路径", alias="w"),
        source: str = Field(..., description="待调试程序源码文件目录", alias="s"),
        mpicmd: str = Field(..., description="需执行的mpirun命令，需使用英文双引号引起来", alias="m"),
        port: int = Field(..., description="Agent Server运行端口号，设置后用于上报启动信息", alias="p"),
        log_level: int = Field(default=1, description="日志级别: 0(DEBUG)/1(INFO)/2(WARNING)/3(ERROR)", alias="l"),
        env: Optional[str] = Field(default=None, description="设置环境变量，需使用英文双引号引起来", alias="e"),
        args: Optional[str] = Field(default=None, description="设置待调试程序运行参数，多个参数用空格隔开", alias="a"),
        threads: Optional[int] = Field(default=None, description="OpenMP应用thread数量", alias="n"),
        help: bool = Field(default=False, description="获取帮助信息", alias="h")
    ) -> Dict:
        """执行HPC调试任务"""

    @mcp.tool()
    def doctor_memalloc(
        help: bool = Field(default=False, description="获取帮助信息"),
        duration: Optional[int] = Field(default=None, description="采集时长(秒)，默认为采集应用运行结束"),
        interval: Optional[int] = Field(default=1, description="采集间隔(秒)，范围1-60"),
        log_level: Optional[int] = Field(default=2, description="日志级别: 0(DEBUG)/1(INFO)/2(WARNING)/3(ERROR)"),
        output: Optional[str] = Field(default=None, description="报告输出路径，默认为当前目录"),
        package: bool = Field(default=False, description="是否将数据导入数据库并生成压缩包"),
        top: Optional[int] = Field(default=5, description="采集内存使用最大的top N个堆栈信息，范围5-15"),
        min_size: Optional[int] = Field(default=None, description="采集内存使用的最小值(字节)，≥1"),
        max_size: Optional[int] = Field(default=None, description="采集内存使用的最大值(字节)，≥2"),
        pid: Optional[int] = Field(default=-1, description="指定采集的进程PID，-1表示采集内核态"),
        workload: Optional[list[str]] = Field(default=None, description="应用的可执行文件路径")
    ) -> Dict:
        """执行内存分配分析任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'doctor', 'memalloc', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if interval and (interval < 1 or interval > 60):
                return {"error": "interval必须在1-60秒之间"}
            if top and (top < 5 or top > 15):
                return {"error": "top必须在5-15之间"}
            if min_size and min_size < 1:
                return {"error": "min_size必须大于等于1"}
            if max_size and max_size < 2:
                return {"error": "max_size必须大于等于2"}

            # 构建命令
            cmd = ['devkit', 'doctor', 'memalloc']

            if duration:
                cmd.extend(['--duration', str(duration)])
            if interval:
                cmd.extend(['--interval', str(interval)])
            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])
            if output:
                cmd.extend(['--output', output])
            if package:
                cmd.append('--package')
            if top:
                cmd.extend(['--top', str(top)])
            if min_size:
                cmd.extend(['--min-size', str(min_size)])
            if max_size:
                cmd.extend(['--max-size', str(max_size)])
            if pid != -1:
                cmd.extend(['--pid', str(pid)])
            if workload:
                cmd.extend(workload)

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            return {
                "result": result,
                "command": " ".join(cmd),
                "output_file": output if output else "MemoryAllocateSummaryReport-*.txt"
            }

        except subprocess.CalledProcessError as e:
            return {
                "error": e.output,
                "command": " ".join(cmd) if 'cmd' in locals() else None
            }
        except Exception as e:
            return {"error": str(e)}
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'debugger', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}
            
            # 参数验证
            if type.lower() != "launch":
                return {
                    "error": "目前仅支持launch方式调试",
                    "suggestions": ["launch"]
                }
            
            # 构建命令
            cmd = [
                'devkit', 'debugger',
                '--type', type,
                '--workload', workload,
                '--source', source,
                '--mpicmd', mpicmd,
                '--port', str(port)
            ]
            
            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])
            if env:
                cmd.extend(['--env', env])
            if args:
                cmd.extend(['--args', args])
            if threads is not None:
                cmd.extend(['--threads', str(threads)])
            
            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )
            
            return {
                "result": result,
                "debug_info": {
                    "type": type,
                    "workload": workload,
                    "source": source,
                    "mpicmd": mpicmd,
                    "port": port,
                    "log_level": log_level,
                    "env": env,
                    "args": args,
                    "threads": threads
                }
            }
            
        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []
            
            if "missing required argument" in error_msg.lower():
                if "--type" in error_msg:
                    missing_params.append("type")
                    suggestions.append("launch")
                if "--workload" in error_msg:
                    missing_params.append("workload")
                    suggestions.append("/path/to/executable")
                if "--source" in error_msg:
                    missing_params.append("source")
                    suggestions.append("/path/to/source")
                if "--mpicmd" in error_msg:
                    missing_params.append("mpicmd")
                    suggestions.append("\"mpirun --allow-run-as-root -np 4\"")
                if "--port" in error_msg:
                    missing_params.append("port")
                    suggestions.append("8080")
            
            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
            
        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def devkit_kat(
        task: Optional[str] = Field(default=None, description="任务类型: analysis/advisor/doctor/porting"),
        args: Optional[str] = Field(default=None, description="任务参数"),
        help: bool = Field(default=False, description="显示帮助信息")
    ) -> Dict:
        """执行devkit kat命令"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'kat', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            if not task:
                return {
                    "error": "必须指定任务类型(--task)",
                    "missing_params": ["task"],
                    "suggestions": ["analysis", "advisor", "doctor", "porting"]
                }

            # 构建命令
            cmd = ['devkit', 'kat', task]
            if args:
                cmd.extend(args.split())

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            return {
                "result": result,
                "command": " ".join(cmd)
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "task" in error_msg:
                    missing_params.append("task")
                    suggestions.append("analysis")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def devkit_kat_train(
        train_data: str = Field(..., description="训练数据文件路径", alias="t"),
        pretrained_model: Optional[str] = Field(default=None, description="预训练模型文件路径", alias="p"),
        output_dir: Optional[str] = Field(default=None, description="输出目录路径", alias="o"),
        log_level: Optional[int] = Field(default=None, description="日志级别: 0/1/2/3", alias="l"),
        help: bool = Field(default=False, description="显示帮助信息", alias="h")
    ) -> Dict:
        """执行KAT训练任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'kat', 'train', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not train_data:
                return {
                    "error": "必须指定训练数据文件(--train-data)",
                    "missing_params": ["train_data"],
                    "suggestions": ["/path/to/train/data"]
                }

            # 构建命令
            cmd = ['devkit', 'kat', 'train', '--train-data', train_data]

            if pretrained_model:
                cmd.extend(['--pretrained-model', pretrained_model])
            if output_dir:
                cmd.extend(['--output-dir', output_dir])
            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果
            output_files = []
            if output_dir:
                output_files.append(f"{output_dir}/model.pth")
                output_files.append(f"{output_dir}/train_log.txt")
            else:
                output_files.append("model.pth")
                output_files.append("train_log.txt")

            return {
                "result": result,
                "command": " ".join(cmd),
                "output_files": output_files
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--train-data" in error_msg:
                    missing_params.append("train_data")
                    suggestions.append("/path/to/train/data")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def devkit_kat_template(
        generate: bool = Field(default=False, description="生成模板文件", alias="g"),
        output: Optional[str] = Field(default=None, description="指定输出目录", alias="o"),
        log_level: Optional[int] = Field(default=None, description="日志级别: 0/1/2/3", alias="l"),
        help: bool = Field(default=False, description="显示帮助信息", alias="h")
    ) -> Dict:
        """执行KAT模板生成任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'kat', 'template', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 构建命令
            cmd = ['devkit', 'kat', 'template']
            
            if generate:
                cmd.append('--generate')
            if output:
                cmd.extend(['--output', output])
            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果
            template_path = None
            if generate:
                if output:
                    template_path = f"{output}/kat_template.json"
                else:
                    template_path = "kat_template.json"

            return {
                "result": result,
                "command": " ".join(cmd),
                "template_generated": generate,
                "template_path": template_path
            }
            
        except subprocess.CalledProcessError as e:
            return {
                "error": e.output,
                "command": " ".join(cmd) if 'cmd' in locals() else None
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def devkit_kat_use(
        input_dir: str = Field(..., description="输入目录路径", alias="i"),
        log_level: Optional[int] = Field(default=None, description="日志级别: 0/1/2/3", alias="l"),
        help: bool = Field(default=False, description="显示帮助信息", alias="h")
    ) -> Dict:
        """执行KAT使用分析任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'kat', 'use', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not input_dir:
                return {
                    "error": "必须指定输入目录(--input-dir)",
                    "missing_params": ["input_dir"],
                    "suggestions": ["/path/to/input/directory"]
                }

            # 构建命令
            cmd = ['devkit', 'kat', 'use', '--input-dir', input_dir]

            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            return {
                "result": result,
                "command": " ".join(cmd),
                "input_dir": input_dir,
                "log_level": log_level
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--input-dir" in error_msg:
                    missing_params.append("input_dir")
                    suggestions.append("/path/to/input/directory")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    @mcp.tool()
    def devkit_advisor_dr_check(
        elf_file: str = Field(..., description="ELF文件路径", alias="f"),
        input_path: Optional[str] = Field(default=None, description="输入路径", alias="i"),
        safe_file: Optional[str] = Field(default=None, description="安全文件路径", alias="s"),
        elf_params: Optional[str] = Field(default=None, description="ELF参数", alias="p"),
        output_path: Optional[str] = Field(default=None, description="报告输出路径", alias="o"),
        shield_file: Optional[str] = Field(default=None, description="屏蔽文件路径", alias="sf"),
        config_file: Optional[str] = Field(default=None, description="配置文件路径", alias="cf"),
        decode_report: Optional[str] = Field(default=None, description="解码报告文件路径", alias="d"),
        summary_report: Optional[bool] = Field(default=None, description="是否生成摘要报告", alias="sr"),
        enable_backtrace: Optional[bool] = Field(default=None, description="是否启用回溯", alias="eb"),
        report_type: Optional[str] = Field(default="all", description="报告类型: all/json/html/csv", alias="r"),
        log_level: Optional[int] = Field(default=1, description="日志级别: 0/1/2/3", alias="l"),
        timeout: Optional[int] = Field(default=None, description="任务超时时间(分钟)"),
        help: bool = Field(default=False, description="获取帮助信息", alias="h")
    ) -> Dict:
        """执行动态重定位检查任务"""
        try:
            if help:
                result = subprocess.check_output(
                    ['devkit', 'advisor', 'dr-check', '--help'],
                    text=True,
                    stderr=subprocess.STDOUT
                )
                return {"help": result}

            # 参数验证
            if not elf_file:
                return {
                    "error": "必须指定ELF文件路径(--elf-file)",
                    "missing_params": ["elf_file"],
                    "suggestions": ["/path/to/executable"]
                }

            # 构建命令
            cmd = ['devkit', 'advisor', 'dr-check', '--elf-file', elf_file]

            if input_path:
                cmd.extend(['--input', input_path])
            if safe_file:
                cmd.extend(['--safe-file', safe_file])
            if elf_params:
                cmd.extend(['--elf-params', elf_params])
            if output_path:
                cmd.extend(['--output', output_path])
            if shield_file:
                cmd.extend(['--shield-file', shield_file])
            if config_file:
                cmd.extend(['--config-file', config_file])
            if decode_report:
                cmd.extend(['--decode', decode_report])
            if summary_report is not None:
                cmd.extend(['--summary-report', 'true' if summary_report else 'false'])
            if enable_backtrace is not None:
                cmd.extend(['--enable-backtrace', 'true' if enable_backtrace else 'false'])
            if report_type:
                cmd.extend(['--report-type', report_type])
            if log_level is not None:
                cmd.extend(['--log-level', str(log_level)])
            if timeout is not None:
                cmd.extend(['--set-timeout', str(timeout)])

            # 执行命令
            result = subprocess.check_output(
                cmd,
                text=True,
                stderr=subprocess.STDOUT
            )

            # 解析结果
            report_paths = {}
            if output_path:
                report_paths = {
                    "json": f"{output_path}/dr_check_report.json",
                    "html": f"{output_path}/dr_check_report.html",
                    "csv": f"{output_path}/dr_check_report.csv"
                }

            return {
                "result": result,
                "command": " ".join(cmd),
                "report_paths": report_paths if report_paths else None
            }

        except subprocess.CalledProcessError as e:
            error_msg = e.output
            missing_params = []
            suggestions = []

            if "missing required argument" in error_msg.lower():
                if "--elf-file" in error_msg:
                    missing_params.append("elf_file")
                    suggestions.append("/path/to/executable")

            return {
                "error": error_msg,
                "missing_params": missing_params if missing_params else None,
                "suggestions": suggestions if suggestions else None,
                "retry": bool(missing_params)
            }
        except Exception as e:
            return {
                "error": str(e),
                "retry": False
            }

    mcp.run()

