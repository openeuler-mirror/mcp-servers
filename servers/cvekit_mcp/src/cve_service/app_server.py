import os
import json
import asyncio
from typing import Dict, Optional
from dotenv import load_dotenv
import logging
from threading import Lock 

from camel.models import ModelFactory
from camel.types import ModelPlatformType
from camel.configs import SiliconFlowConfig
from camel.agents import CallbackMCPAgent

from a2a.types import (
    AgentSkill, AgentCard, AgentCapabilities, TextPart
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.utils import new_task
from typing_extensions import override



SYS_MSG = """
You are a helpful assistant, and you prefer to use tools provided by the user 
to solve problems. Note: You will complete tasks independently without requiring user verification during the process.
Using a tool, you will tell the user `server_idx`, `tool_name` and 
`tool_args` formatted in JSON as following:
```json
{
    "server_idx": idx,
    "tool_name": "tool_name",
    "tool_args": {
        "arg1": value1,
        "arg2": value2,
        ...
    }
}
```
Otherwise, you should respond to the user directly.
"""


def validate_request(data: Dict) -> Optional[str]:
    """验证请求参数"""
    action = data.get("action")
    if not action or action not in ["branches-analysis", "patch-apply-pr-creation","pipeline"]:
        return "action 参数必须是 'branches-analysis'、'patch-apply-pr-creation'、'pipeline'"

    if not data.get("cve_id"):
        return "cve_id 参数缺失"

    if action == "patch-apply-pr-creation" and not (data.get("branches") and data.get("signer_name") and data.get("signer_email")):
        return "patch-apply-pr-creation 操作必须提供 branches, signer-name, signer-email 参数"
    if action == "pipeline" and not (data.get("branches") and data.get("signer_name") and data.get("signer_email")):
        return "pipeline 操作必须提供 branches, signer-name, signer-email 参数"

    return None


def build_config_from_request(data: Dict) -> Dict:
    """从请求构建配置"""
    
    # 获取 gitee token,不提供默认值
    gitee_token = os.getenv("GITEE_TOKEN") or data.get("gitee_token")
    if not gitee_token:
        raise ValueError("必须提供 GITEE_TOKEN(环境变量或请求参数)")
    
    return {
        "fork_repo_url": data.get("fork_repo", os.getenv("DEFAULT_FORK_REPO")),
        "target_repo_url": data.get("target_repo", os.getenv("DEFAULT_TARGET_REPO")),
        "clone_path": data.get("clone_path", os.getenv("DEFAULT_CLONE_PATH")),
        "gitee_token": gitee_token,
        "signer_name": data.get("signer_name"),
        "signer_email": data.get("signer_email"),
        "branches": data.get("branches"),
        "openai_key": data.get("openai_key", os.getenv("SILICONFLOW_API_KEY")),
        "llm_provider": data.get("llm_provider", os.getenv("LLM_PROVIDER"))
    }

def build_agent_message(action: str, data: Dict, config: Dict) -> str:
    """构建发送给 agent 的消息（优化后更易被 agent 解析）"""
    # 关键配置信息（JSON格式化，便于解析）
    base_config = json.dumps({
        "fork_repo_url": config["fork_repo_url"],
        "target_repo_url": config["target_repo_url"],
        "clone_path": config["clone_path"],
        "gitee_token": config["gitee_token"],
        "llm_provider": config["llm_provider"],
        "openai_key": config["openai_key"],
        "signer": {"name": data.get("signer_name"), "email":data.get("signer_email")}
    }, ensure_ascii=False)

    if action == "branches-analysis":
        return (
            f"【任务】CVE分支分析与适配检查\n"
            f"【核心指令】1. 基于CVE-ID分析指定分支的漏洞引入情况与补丁适配状态；2. 生成含完整字段的分析表格；3. 以多选题格式列出待应用分支（含适配状态/补丁路径/差异文件）；4. 展示全部信息，等待用户选择分支；5. 暂不执行补丁应用与PR提交\n"
            f"【参数】CVE_ID: {data.get('cve_id')}, 全量分支列表: {os.getenv('DEFAULT_BRANCHES')}\n"
            f"【基础配置】{base_config}\n"
            f"【注意】为了完成这一步，你需要依次执行前置CVE修复流程的前四步，而不是直接执行第四步 analyze_branches"
        )
    elif action == "patch-apply-pr-creation":
        return (
            f"【任务】CVE补丁应用与PR创建\n"
            f"【核心指令】1. 将指定补丁应用到目标分支；2. 按签名信息提交代码；3. 为该CVE创建PR至目标仓库\n"
            f"【参数】CVE_ID: {data.get('cve_id')}, 目标分支列表: {data.get('branches')}\n"
            f"【基础配置】{base_config}"
            f"【注意】为了完成这一步，你需要执行CVE修复流程的第五步apply-patch和第六步create-pr，注意！前序CVE分支分析与适配检查步骤已经完成，不要重复执行CVE修复流程的前四步\n"
            f"【注意】需按分支列表顺序逐一处理，确保每个分支的补丁应用与PR创建独立完成。"
        )
    elif action == "pipeline":
        return (
            f"【任务】CVE修复流程\n"
            f"【核心指令】1. 分析CVE补丁；2. 适配CVE补丁；3. 应用CVE补丁；4. 创建PR\n"
            f"【参数】CVE_ID: {data.get('cve_id')}， 全量分支列表{os.getenv('DEFAULT_BRANCHES')}， 待应用补丁和提交pr分支列表{data.get('branches')} \n"
            f"【基础配置】{base_config}\n"
            f"【注意】请依次执行CVE修复流程的所有步骤，直至pr创建完毕\n"
            f"【注意】分支分析（analyze_branches）需覆盖全量分支 {os.getenv('DEFAULT_BRANCHES')}；\n"
            f"【注意】补丁应用（apply-patch）与PR创建（create-pr）仅针对目标分支列表 {data.get('branches')}；\n"
            f"【注意】所有步骤自动串联执行，直至PR创建完成，无需中途等待用户确认。"
        )


async def create_mcp_agent(
    model_type: str = "",
    local_config: str = "",
    task_updater: Optional[TaskUpdater] = None 
) -> CallbackMCPAgent:
    """创建 MCP Agent"""
    try:
        load_dotenv()
        model = ModelFactory.create(
            model_platform=ModelPlatformType.SILICONFLOW,
            model_type=model_type,
            model_config_dict=SiliconFlowConfig(
                temperature=0.2, stream=False
            ).as_dict(),
        )
        return CallbackMCPAgent(
            system_message=SYS_MSG,
            model=model,
            local_config_path=local_config,
            function_calling_available=False,
            task_updater=task_updater 
        )
    except Exception as e:
        raise RuntimeError(f"初始化 MCPAgent 失败: {str(e)}")


class CVEAgentExecutor(AgentExecutor):
    def __init__(self):
        load_dotenv()
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """执行 CVE 任务"""
        local_agent: Optional[CallbackMCPAgent] = None
        local_task_updater: Optional[TaskUpdater] = None

        try:
            try:
                message_content = context.get_user_input()
                task_params = json.loads(message_content) if message_content else {}
                print(task_params)
            except json.JSONDecodeError as e:
                task = new_task(context.message)
                local_task_updater = TaskUpdater(event_queue, task.id, task.context_id)
                error_msg = f"请求参数解析失败：{str(e)}（输入内容：{message_content}）"
                error_message = local_task_updater.new_agent_message(parts=[TextPart(text=error_msg)])
                await local_task_updater.failed(message=error_message)
                await event_queue.enqueue_event(task)
                return

            validate_msg = validate_request(task_params)
            if validate_msg:
                task = new_task(context.message)
                local_task_updater = TaskUpdater(event_queue, task.id, task.context_id)
                error_message = local_task_updater.new_agent_message(parts=[TextPart(text=validate_msg)])
                await local_task_updater.failed(message=error_message)
                await event_queue.enqueue_event(task)
                return

            try:
                config = build_config_from_request(task_params)
            except ValueError as e:
                task = new_task(context.message)
                local_task_updater = TaskUpdater(event_queue, task.id, task.context_id)
                error_message = local_task_updater.new_agent_message(parts=[TextPart(text=str(e))])
                await local_task_updater.failed(message=error_message)
                await event_queue.enqueue_event(task)
                return

            task = new_task(context.message)
            local_task_updater = TaskUpdater(event_queue, task.id, task.context_id)
            await event_queue.enqueue_event(task)  

            action = task_params.get("action")
            agent_message = build_agent_message(action, task_params, config)
            print(f"【任务 {task.id}】Agent Message:{agent_message}")

            local_agent = await create_mcp_agent(
                model_type=os.getenv("DEFAULT_MODEL_TYPE"),
                local_config=os.getenv("DEFAULT_LOCAL_CONFIG"),
                task_updater=local_task_updater
            )

            async def agent_run():
                return await local_agent.astep(agent_message)
            timeout = int(os.getenv("TIMEOUT", 300)) 
            try:
                response = await asyncio.wait_for(agent_run(), timeout=timeout) 
            except asyncio.TimeoutError:
                error_msg = f"Task {task.id} execution timeout (exceeded {timeout/60} minutes)"
                logging.error(error_msg)
                error_message = local_task_updater.new_agent_message(parts=[TextPart(text=error_msg)])
                await local_task_updater.failed(message=error_message)
                return

            result = str(response) if response else "无返回结果"
            print(f"【任务 {task.id}】执行结果:{result}")

            await local_task_updater.add_artifact(
                parts=[TextPart(text=result)],
                name="final_result",
                last_chunk=True,
            )
            await local_task_updater.complete()

        except Exception as e:
            error_msg = f"【任务 {task.id if 'task' in locals() else '未知'}】处理请求时出错: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            if local_task_updater:
                error_message = local_task_updater.new_agent_message(parts=[TextPart(text=error_msg)])
                await local_task_updater.failed(message=error_message)
        finally:
            if local_agent:
                try:
                    await local_agent.disconnect()
                except Exception as e:
                    print(f"【任务 {task.id if 'task' in locals() else '未知'}】断开 agent 连接时出错: {e}")

    @override
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue
    ) -> None:
        """取消任务"""
        task_updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id
        )
        
        
        try:
            await task_updater.cancel()
            logging.info(f"任务 {context.task_id} 已取消")
        except Exception as e:
            message = task_updater.new_agent_message(
                parts=[TextPart(text=f"取消任务 {context.task_id} 失败: {str(e)}")]
            )
            await task_updater.failed(message=message)

class ConcurrentSafeInMemoryTaskStore(InMemoryTaskStore):
    """并发安全的内存任务存储（添加锁保护）"""
    def __init__(self):
        super().__init__()
        self._lock = Lock()  # 线程锁，保护读写操作

    def get_task(self, task_id: str):
        with self._lock:  # 读操作加锁
            return super().get_task(task_id)

    def save_task(self, task):
        with self._lock:  # 写操作加锁
            return super().save_task(task)

    def update_task(self, task):
        with self._lock:  # 更新操作加锁
            return super().update_task(task)
        
# 定义技能
skills = [
    AgentSkill(
        id="cve_branches_analysis",
        name="CVE分支分析与适配检查",
        description="分析 CVE 漏洞在各个分支上的影响并执行修复前的步骤",
        tags=["cve", "branches", "analysis"],
        examples=[
            "分析 CVE-2023-0001 在各分支的影响",
            '{"action": "branches-analysis", "cve_id": "CVE-2023-0001"}'
        ]
    ),
    AgentSkill(
        id="cve_patch_apply_pr_creation",
        name="CVE补丁应用与PR创建",
        description="为已修复的 CVE 漏洞创建 PR 提交到目标仓库",
        tags=["cve","patch","apply", "pr", "creation"],
        examples=[
            "为 CVE-2023-0001 创建 PR",
            '{"action": "pr-creation", "cve_id": "CVE-2023-0001", "branches": "OLK-6.6"}'
        ]
    ),
    AgentSkill(
        id="cve_pipeline",
        name="CVE修复全流程",
        description="为已修复的 CVE 漏洞创建 PR 提交到目标仓库",
        tags=["cve","pipeline"],
        examples=[
            "为 CVE-2023-0001 创建 PR",
            '{"action": "pipeline", "cve_id": "CVE-2023-0001"}'
        ]
    )
]

# 创建 agent card
agent_card = AgentCard(
    name="CVE 处理智能体",
    description="用于处理 CVE 漏洞分析、修复和 PR 创建的智能体",
    url="http://localhost:9991/",
    version="1.0.0",
    defaultInputModes=["text/plain", "application/json"],
    defaultOutputModes=["text/plain", "application/json"],
    capabilities=AgentCapabilities(streaming=True),
    skills=skills,
)

request_handler = DefaultRequestHandler(
    agent_executor=CVEAgentExecutor(),
    task_store=ConcurrentSafeInMemoryTaskStore(),)

app = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler)


starlette_app = app.build()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 9991))
    uvicorn.run(starlette_app, host="0.0.0.0", port=port, log_level="debug", workers=1)
