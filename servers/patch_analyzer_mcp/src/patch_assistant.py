from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import contextvars
import csv
import json
import os
import threading
import time
import re
from typing import Any, Dict, List, Optional

from cachetools import LRUCache
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from openai import BadRequestError
import openai
import pandas as pd
from pydantic import BaseModel, Field
from queue import Queue
import tools

# 创建FastMCP实例，http方式
mcp = FastMCP(instructions="生成补丁、解析补丁、回合补丁", host="0.0.0.0", port=8100)

user_config_cache = LRUCache(maxsize=10000)
default_config ={}
client_config = {}
# 配置OpenAI客户端 openai v1.100.1
client = OpenAI(
    api_key="xxxxx", 
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

class CSVWriterService:
    """
        分析结果逐步固化到csv中间文件
    """
    def __init__(self, filename, interval=300):
        self.filename = filename
        self.interval = interval
        self._queue = Queue()
        self._lock = threading.Lock()
        self._start_writer_thread()
        self._init_file()
    
    def _init_file(self):
        if not os.path.exists(self.filename):
            with open(self.filename, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["提交信息","提交时间","模块","改动说明","判断理由","合入策略","确认合入","确认理由","提交标题","补丁类型","commit_url","提交描述","差异","patch名"])
    
    def _start_writer_thread(self):
        def loop():
            while True:
                self._flush_to_csv()
                time.sleep(self.interval)
        threading.Thread(target=loop, daemon=True).start()

    def _flush_to_csv(self):
        batch = []
        while not self._queue.empty():
            batch.append(self._queue.get())
        
        if not batch:
            return

        with self._lock:
            with open(self.filename, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for item in batch:
                    writer.writerow([item["提交信息"],item["提交时间"],item["模块"],item["改动说明"],item["判断理由"],item["合入策略"],item["确认合入"],item["确认理由"],item["提交标题"],item["补丁类型"],item["commit_url"],item["提交描述"],item["差异"],item["patch名"]])
    
    def add_data(self, data):
        self._queue.put(data)


def check_json_output(output: str) -> str:
    """判断llm是否包含<think>标签，检查json格式完整性"""
    cleaned_output = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL)
    cleaned_output = cleaned_output.lstrip()  # 去除多余段首空白
        
    # 检查剩余内容是否为JSON格式
    try:
        llm_data = json.loads(cleaned_output)
        return llm_data
    except json.JSONDecodeError:
        raise json.JSONDecodeError(f"数据不满足json格式", cleaned_output, 0)


def estimate_tokens(text: str) -> int:
    """
        粗略估算长文本转换token后长度，中文按照1token平均1.5字符，英文1token平均4字符
    """
    char_count = len(text)
    token_len = 0
    zh_char = 0
    en_char = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            zh_char += 1
        else:
            en_char += 1
    token_len = int(zh_char / 1.5 + en_char / 4)
    return token_len

def call_vllm(service: CSVWriterService, software_name: str, system_prompt: str, query:str, idx: int):
    patch_content = tools.read_patch(software_name, idx)
    content = patch_content.get("提交描述", None)
    diff = patch_content.get("差异", None)
    patch_content["确认合入"] = ""
    patch_content["确认理由"] = ""
    query += json.dumps(content, ensure_ascii=False, indent=2)
    diff_token = estimate_tokens(json.dumps(diff, ensure_ascii=False, indent=2))
    if diff_token < 8192:
        query += json.dumps(diff, ensure_ascii=False, indent=2)

    #llm结果不满足预期将重试三次
    max_retries = 3
    retry_count = 0
    terminated = False
    final_content = {}
    final_content.update(patch_content)
    while retry_count < max_retries and not terminated:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        try:
            # 调用OpenAI模型
            response = client.chat.completions.create(
                model=client_config.get("model_name"),
                messages=messages,
                temperature=float(client_config.get("temperature")),
                top_p=float(client_config.get("top_p")),
                timeout=int(client_config.get("timeout"))
            )
            response_message = response.choices[0].message.content
        except BadRequestError as e:
            print(f"补丁{idx} llm分析报错： {e}，正在进行第{retry_count}次重试...")
            retry_count += 1
            continue
        except Exception as e:
            print(f"补丁{idx} llm分析报错： {e}，正在进行第{retry_count}次重试...")
            retry_count += 1
            continue
        
        try:
            llm_data = check_json_output(response_message)
            final_content.update(llm_data)
            service.add_data(final_content)
            print(f"分析补丁{idx}已完成")
            terminated = True
        except json.JSONDecodeError:
            retry_count += 1
            print(f"补丁{idx}分析输出格式不正确，正在进行第{retry_count}次重试...")
            
            query += f"，你输出的内容是：{response_message}，格式不符合要求。\n" \
                        f"请严格按照要求格式重新生成，确保输出是有效的纯JSON内容。"
        
    if not terminated:
        service.add_data(final_content)
        print(f"补丁{idx}经过{max_retries}次重试后仍无法解析，跳过这条数据分析")


def gen_patch_content(service: CSVWriterService, software_name: str, system_prompt: str, query: str, commit_id: str):
    """分析补丁内容"""
    patch_count = tools.get_patch_count(software_name, commit_id)
    print(f"补丁总数: {patch_count}，开始逐条分析")

    with ThreadPoolExecutor(max_workers=int(client_config.get("max_workers"))) as executor:
        idx = 1
        futures = set()
        
        while idx <= patch_count or futures:
            while len(futures) < int(client_config.get("max_workers")) and idx <= patch_count:
                future = executor.submit(call_vllm, service, software_name, system_prompt, query, idx)
                futures.add(future)
                idx += 1
            
            if futures:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                
                # 处理已完成的任务
                for future in done:
                    try:
                        future.result(timeout=60)
                    except Exception as e:
                        print(f"分析补丁失败: {str(e)}")
    
    service._flush_to_csv()
    print(f"所有补丁已分析完成！")



def process_with_flow(software_name: str, patch_content: List[Dict]) -> str:
    """补丁内容超长时由工作流驱动触发补丁回合动作"""
    try:
        result = tools.apply_patch(software_name, patch_content)
    except Exception as e:
        result = f"处理补丁时发生错误：{str(e)}"

    return result


def excel_to_json(excel_path: str, sheet_name: str = 0) -> List[Dict]:
    """
    将Excel文件转换为JSON格式（每行作为标题，每列作为数据条目）
    
    参数:
        excel_path: Excel文件路径
        sheet_name: 工作表名称或索引（默认0，即第一个工作表）
    
    返回:
        转换后的JSON数据列表
    """
    try:
        # 读取Excel文件，第一行为标题行
        df = pd.read_excel(
            excel_path, 
            sheet_name=sheet_name, 
            header=0,
            index_col=False
        )
        
        # 检查数据是否为空
        if df.empty:
            raise ValueError("Excel文件中没有有效数据")
        
        # 转换为JSON格式列表（每条记录对应一行数据）
        json_data = df.to_dict(orient="records")
        # 删除'提交描述'和'差异'字段，占用token影响上下文长度
        fields_to_remove = ['提交描述', '差异']
        for item in json_data:
            for field in fields_to_remove:
                # 若字段存在则删除，避免KeyError
                if field in item:
                    del item[field]
        return json_data
    
    except FileNotFoundError:
        raise FileNotFoundError(f"未找到Excel文件: {excel_path}")
    except Exception as e:
        raise Exception(f"转换失败: {str(e)}")


def load_config(config_filename: str = "assistant.conf"):
    """
    读取配置文件
    参数:
        config_filename: 配置文件名（默认"config.txt"）
    返回:
        配置字典（key: 配置项名, value: 配置值（字符串类型））
    """
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    config_file_path = os.path.join(script_dir, config_filename)
    try:
        with open(config_file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    print(f"警告：配置文件第{line_num}行格式错误（缺少'='），已跳过该行：{line}")
                    continue
                key, value = line.split("=", 1)
                client_config[key.strip()] = value.strip()

        global client
        client = OpenAI(
            api_key=client_config.get("api_key"), 
            base_url=client_config.get("base_url")
        )

        global default_config
        default_config = {
            "patch_excel_gen_path": client_config.get("patch_excel_gen_path"),
            "judge_rules": client_config.get("judge_rules")
        }
        user_config_cache["root"] = default_config
        return
    
    except FileNotFoundError:
        raise FileNotFoundError(f"未找到配置文件：{config_file_path}")
    except Exception as e:
        raise Exception(f"读取配置文件失败：{str(e)}")


def get_current_auth() -> str:
    ctx = mcp.get_context()
    request_context = ctx.request_context
    token = request_context.request.headers.get("authorization")
    if not token:
        token = "root"

    return token


@mcp.tool()
def set_client_config(config_key: str, config_value: str):
    """
        设定指定配置参数的值，可以设置
            patch_excel_gen_path:补丁分析结果excel文件输出的根路径；
            judge_rules:评审补丁回合规则
        参数:
            config_key: 键（必须为字符串）
            config_value: 值（支持任意类型）
        返回: 设置值结果是否成功
    """
    if not isinstance(config_key, str):
        print(f"键必须是字符串类型，当前传入 {type(config_key)}")
        return {
            "status": "done",
            "message": "设置失败，键类型不匹配"
        }
    token = get_current_auth()
    ctx = user_config_cache.get(token, {})
    if not ctx:
        global default_config
        new_ctx = default_config.copy()
        new_ctx[config_key] = config_value
        user_config_cache[token] = new_ctx
        return {
            "status": "done",
            "message": "设置成功"
        }
    new_ctx = ctx.copy()
    new_ctx[config_key] = config_value
    user_config_cache[token] = new_ctx

    return {
        "status": "done",
        "message": "设置成功"
    }


@mcp.tool()
def get_client_config(config_key: str):
    """
        获取系统预设或者用户更新后指定配置参数的值，可以获取到
            patch_excel_gen_path:补丁分析结果excel文件输出的根路径；
            judge_rules:评审补丁回合规则
        参数:
            config_key: 要查询配置的键（必须为字符串）
        返回: 查询成功返回键对应的值，失败返回错误信息
    """
    if not isinstance(config_key, str):
        print(f"键必须是字符串类型，当前传入 {type(config_key)}")
        return {
            "status": "done",
            "message": "查询失败，键类型不匹配"
        }
    token = get_current_auth()
    ctx = user_config_cache.get(token, {})
    if not ctx:
        global default_config
        value = default_config.get(config_key, None)
        return {
            "status": "done",
            "message": value
        }
    value = ctx.get(config_key, None)

    return {
        "status": "done",
        "message": value
    }


@mcp.tool()
def analyse_software_patch(software_name: str, commit_id: str):
    """
        通过用户输入的软件名、commit_id分析软件历史补丁详细内容，结果生成excel分析文档
    
        规则:
            需要提前设置的变量-> patch_excel_gen_path补丁分析结果excel文件输出的根路径；
        
        参数:
            software_name: 需要分析的软件名
            commit_id: 需要分析的软件起始补丁对应的提交信息commit id
            
        返回:
            分析结果
    """

    print("收到用户输入，接下来执行软件漏洞补丁分析...")
    token = get_current_auth()
    ctx = user_config_cache.get(token, {})
    judge_rules = ctx.get("judge_rules", None)
    if judge_rules is None:
        judge_rules = client_config.get("judge_rules")
    system_prompt = f'''你是一个AI辅助补丁分析工具，可以结合提供的工具来帮助回答用户的问题。
        请根据问题判断是否需要调用工具，如果需要，请选择合适的工具并正确指定参数。
        工具调用结果返回后，请结合结果逐项分析给出最终回答，分析结果按照要求返回，所有的结果都是有用的，请不要遗漏。
        如果不需要调用工具，可以直接回答问题。
        你需要遵守以下规则：
        1、分析结果需要完整，不可以遗漏。
        2、你给出的最终结果将按照纯json格式被解析，返回结果请严格按照以下json格式，不要包含任何格式(例如MarkDown```json)，也不要添加解释。
        以下是补丁分析举例：
        补丁分析输入："From 860874bd1cca5142eb23d123a0aeac7ec9d73d75 Mon Sep 17 00:00:00 2001\nFrom: zhaolichang <zhaolichang@huawei.com>\n
            Date: Fri, 21 Mar 2025 01:08:48 +0800\nSubject: [PATCH 1/4] PINCTRL: Fix the issue that CONFIG_PINCTRL_AMD do not\n 
            support m option\n\nhuawei inclusion\ncategory: bugfix\nbugzilla: https://gitee.com/src-openeuler/calamares/issues/IBS0LG\n
            CVE: NA\n\nFix the issue that the CONFIG_PINCTRL_ADM configuration do not\n
            support the 'm' (module) option, and change it to 'y' (built-in).\n\nFixes: cbba3eb02aa9 ("PINCTRL:ENABLE_CONFIG_PINCTRL_AMD")\n
            Signed-off-by: zhaolichang <zhaolichang@huawei.com>\n---\n arch/arm64/configs/openeuler_defconfig | 1 +-\n 
            1 files changed, 1 insertions(+), 1 deletions(-)\n\ndiff --git a/arch/arm64/configs/openeuler_defconfig b/arch/arm64/configs/openeuler_defconfig\n
            index 531f5f04d8e8..39729694001b 100644\n--- a/arch/arm64/configs/openeuler_defconfig\n+++ b/arch/arm64/configs/openeuler_defconfig\n
            @@ -3945,7 +3945,7 @@ CONFIG_PINMUX=y\n CONFIG_PINCONF=y\n CONFIG_GENERIC_PINCONF=y\n # CONFIG_DEBUG_PINCTRL is not set\n
            -CONFIG_PINCTRL_AMD=m\n+CONFIG_PINCTRL_AMD=y\n # CONFIG_PINCTRL_CY8C95X0 is not set\n # CONFIG_PINCTRL_MCP23S08 is not set\n 
            # CONFIG_PINCTRL_MICROCHIP_SGPIO is not set\n--\n2.43.0"
        结果输出格式为：
        {{
            "提交信息": "860874bd1cca5142eb23d123a0aeac7ec9d73d75",
            "提交时间": "Fri, 21 Mar 2025 01:08:48 +0800",
            "模块": "PINCTRL",
            "改动说明": "修复 CONFIG_PINCTRL_AMD 配置不支持模块（'m'）选项的问题，将其修改为内置（'y'）方式",
            "判断理由": "xxxx",
            "合入策略": "是",
            "提交标题": "PINCTRL: Fix the issue that CONFIG_PINCTRL_AMD do not support m option",
            "补丁类型": "bugfix"
        }}
        参数解释：
        提交信息--补丁信息中对应的补丁编号；
        提交时间--commit修改时间；
        模块--补丁修改涉及的文件所属模块，通常在提交标题中会显示；
        改动说明--补丁信息中对补丁修改点的描述,使用中文生成回答，计算机相关专有名词使用英文表述；
        判断理由--基于以下几点分析：{judge_rules}；
        合入策略--是/否，根据“判断理由”设置是否需要回合；
        提交标题--commit的标题，从补丁信息中提取，格式为“模块：修改内容”；
        补丁类型--根据合入策略分析结果代码的改动属于哪一类型；
    '''

    user_query = "帮我分析" + software_name + "的补丁，最终结果以json格式输出，补丁内容如下： "

    try:
        now = datetime.now()

        patch_excel_gen_path = ctx.get("patch_excel_gen_path", None)
        if patch_excel_gen_path is None:
            patch_excel_gen_path = client_config.get("patch_excel_gen_path")
        csv_file = patch_excel_gen_path + "/" + software_name + "-" + now.strftime("%Y%m%d%H%M%S") + ".csv"
        service = CSVWriterService(csv_file, 300)
        gen_patch_content(service, software_name, system_prompt, user_query, commit_id)
        df = pd.read_csv(csv_file)
        excel_file = patch_excel_gen_path + "/" + software_name + "-" + now.strftime("%Y%m%d%H%M%S") + ".xlsx"
        df.to_excel(excel_file, index=False)
        result = f"补丁分析文件已生成到：{excel_file}"
    except Exception as e:
        result = f"处理补丁时发生错误：{str(e)}"
        
    return {
        "status": "done",
        "message": result
    }


@mcp.tool()
def apply_software_patch(software_name: str, patch_excel_path: str):
    """
        通过用户输入的软件名、excel评审文档路径，解析excel，回合软件补丁
        
        参数:
            software_name: 需要分析的软件名
            commit_id: 软件补丁对应的提交信息commit id
            
        返回:
            回合补丁是否成功
    """

    print("收到用户输入，接下来执行软件patch回合...")
    patch_list = excel_to_json(patch_excel_path)
    filter_list = [item for item in patch_list if item.get("确认合入") == "是"]
    if not filter_list:
        return f"{patch_excel_path}文件导入后'确认合入'的补丁为空，请确认"
    result = process_with_flow(software_name, filter_list)

    final_result = f"补丁回合处理结果：{result}"
    return {
        "status": "done",
        "message": final_result
    }


def get_patch_name_by_commit_id(json_data, commit_id) -> str:
    """
    从excel数据中根据commit id查找对应的patch name值，并处理文件名格式
    """
    for item in json_data:
        if '提交信息' in item and 'patch名' in item:
            if item['提交信息'] == commit_id:
                patch_name = item['patch名']
                # 按第一个"-"进行截断
                if '-' in patch_name:
                    prefix_part = patch_name.split('-', 1)[0]
                    return prefix_part

    # 未找到匹配项时返回空字符串
    return ""


@mcp.tool()
def re_analyse_patch(software_name: str, commit_id: str, patch_excel_path: str):
    """
        通过用户输入的软件名、excel评审文档路径，指定的commit_id按照新规则重新分析单个commit id对应的补丁内容
    
        规则:
            需要提前设置的变量-> judge_rules: 用户自定义的补丁评审规则
        
        参数:
            software_name: 需要分析的软件名
            commit_id: 软件补丁对应的提交信息commit id
            patch_excel_path: 上一次完整补丁分析报告输出路径
            
        返回:
            单个补丁的分析内容
    """
    print("收到用户输入，接下来执行单条补丁重分析...")
    patch_list = excel_to_json(patch_excel_path)
    patch_idx = get_patch_name_by_commit_id(patch_list, commit_id)
    if patch_idx == "":
        return f"分析原文件{patch_excel_path}中找不到{commit_id}数据，请检查"
    token = get_current_auth()
    ctx = user_config_cache.get(token, {})
    judge_rules = ctx.get("judge_rules", None)
    if judge_rules is None:
        judge_rules = client_config.get("judge_rules")
    system_prompt = f'''你是一个AI辅助补丁分析工具，可以结合提供的工具来帮助回答用户的问题。
        请根据问题判断是否需要调用工具，如果需要，请选择合适的工具并正确指定参数。
        工具调用结果返回后，请结合结果逐项分析给出最终回答，分析结果按照要求返回，所有的结果都是有用的，请不要遗漏。
        如果不需要调用工具，可以直接回答问题。
        你需要遵守以下规则：
        1、分析结果需要完整，不可以遗漏。
        2、你给出的最终结果将按照纯json格式被解析，返回结果请严格按照以下json格式，不要包含任何格式(例如MarkDown```json)，也不要添加解释。
        以下是补丁分析举例：
        补丁分析输入："From 860874bd1cca5142eb23d123a0aeac7ec9d73d75 Mon Sep 17 00:00:00 2001\nFrom: zhaolichang <zhaolichang@huawei.com>\n
            Date: Fri, 21 Mar 2025 01:08:48 +0800\nSubject: [PATCH 1/4] PINCTRL: Fix the issue that CONFIG_PINCTRL_AMD do not\n 
            support m option\n\nhuawei inclusion\ncategory: bugfix\nbugzilla: https://gitee.com/src-openeuler/calamares/issues/IBS0LG\n
            CVE: NA\n\nFix the issue that the CONFIG_PINCTRL_ADM configuration do not\n
            support the 'm' (module) option, and change it to 'y' (built-in).\n\nFixes: cbba3eb02aa9 ("PINCTRL:ENABLE_CONFIG_PINCTRL_AMD")\n
            Signed-off-by: zhaolichang <zhaolichang@huawei.com>\n---\n arch/arm64/configs/openeuler_defconfig | 1 +-\n 
            1 files changed, 1 insertions(+), 1 deletions(-)\n\ndiff --git a/arch/arm64/configs/openeuler_defconfig b/arch/arm64/configs/openeuler_defconfig\n
            index 531f5f04d8e8..39729694001b 100644\n--- a/arch/arm64/configs/openeuler_defconfig\n+++ b/arch/arm64/configs/openeuler_defconfig\n
            @@ -3945,7 +3945,7 @@ CONFIG_PINMUX=y\n CONFIG_PINCONF=y\n CONFIG_GENERIC_PINCONF=y\n # CONFIG_DEBUG_PINCTRL is not set\n
            -CONFIG_PINCTRL_AMD=m\n+CONFIG_PINCTRL_AMD=y\n # CONFIG_PINCTRL_CY8C95X0 is not set\n # CONFIG_PINCTRL_MCP23S08 is not set\n 
            # CONFIG_PINCTRL_MICROCHIP_SGPIO is not set\n--\n2.43.0"
        结果输出格式为：
        {{
            "提交信息": "860874bd1cca5142eb23d123a0aeac7ec9d73d75",
            "模块": "PINCTRL",
            "改动说明": "修复 CONFIG_PINCTRL_AMD 配置不支持模块（'m'）选项的问题，将其修改为内置（'y'）方式",
            "判断理由": "xxxx",
            "合入策略": "是"
        }}
        参数解释：
        提交信息--补丁信息中对应的补丁编号；
        改动说明--补丁信息中对补丁修改点的描述,使用中文生成回答，计算机相关专有名词使用英文表述；
        判断理由--基于以下几点分析：{judge_rules}；
        合入策略--是/否，根据“判断理由”设置是否需要回合；
    '''

    user_query = "帮我分析" + software_name + "的补丁，最终结果以json格式输出，补丁内容如下： "
    try:
        patch_content = tools.read_patch(software_name, int(patch_idx))
        content = patch_content.pop("提交描述", None)
        user_query += json.dumps(content, ensure_ascii=False, indent=2)
        diff = patch_content.pop("差异", None)
        diff_token = estimate_tokens(json.dumps(diff, ensure_ascii=False, indent=2))
        if diff_token < 8192:
            user_query += json.dumps(diff, ensure_ascii=False, indent=2)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]
            
        # 调用OpenAI模型
        response = client.chat.completions.create(
            model=client_config.get("model_name"),
            messages=messages,
            temperature=float(client_config.get("temperature")),
            top_p=float(client_config.get("top_p")),
            timeout=int(client_config.get("timeout"))
        )
        response_message = response.choices[0].message.content
        result = response_message
    except Exception as e:
        result = f"处理补丁分析时发生错误：{str(e)}"
        
    return {
        "status": "done",
        "message": result
    }

if __name__ == "__main__":
    load_config()
    mcp.run("streamable-http")
