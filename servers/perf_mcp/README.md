# Perf进程性能分析MCP

## 功能简介

提供CPU性能分析以及火焰图生成功能以及一些硬件信息获取的基本功能，含有14种基本工具

* top_collect_tool:获取资源消耗top n的工具
* get_process_info_tool：获取进程详细信息的工具
* process_name_to_pid_tool：将进程名称转换为pid的工具
* perf_collect_tool：perf.data采集攻击
* install_perf_tool：perf安装工具
* generate_flamegraph_tool：火焰图生成工具
* get_current_time_tool：获取当前系统时间的工具
* write_text_to_file_tool：将文本写入文件的工具
* get_memory_usage_tool：获取内存使用情况的工具
* get_cpu_usage_tool：获取cpu使用情况的工具
* get_disk_usage_tool：获取磁盘使用情况的工具
* get_directory_files_info_tool：获取目录下信息的工具
* get_system_info_tool：获取系统信息的工具
* get_cpu_details_tool：获取cpu信息的工具

##  使用说明

* 需要root权限
* perf生成的perf.svg会存放在src目录下，并通过时间+进程pid标识
* 通过运行src目录下的server.py启动服务
* 通过修改src目录下的config.yaml中的language字段为zh或en调整服务输出中文或者英文