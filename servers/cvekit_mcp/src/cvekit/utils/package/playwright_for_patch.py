import os
import re
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(BASE_DIR, "playwright_mcp.json")

import logging
 
logger = logging.getLogger(__name__)
 
# 尝试导入cve_service，如果失败则提供替代方案
from cve_service.app_server import create_mcp_agent

def build_cve_patch_prompt(issue_url: str, package_name: str, cve_id: str) -> str:
    return f"""
【任务】使用Playwright MCP浏览网页并跳转链接，找到 {package_name} 的 {cve_id} 修复commit/patch。
1) 从入口页 {issue_url} 出发，找到最可信的修复commit或patch链接
2) 只输出极简JSON（不要输出其他内容）

要求（节省上下文/Token）：
- 只看与 {cve_id}、{package_name}、fix/patch/commit/PR/MR 相关内容
- 每个页面只提取关键证据，避免长段复制
- 最多跳转 5 个页面
- 若有多个候选，优先：明确提到 {cve_id} > 官方仓库 > 直接修复commit > 非大规模roll/合并
- 不确定时返回 not_found，不要猜

判断patch是否是该CVE修复的依据（用于reason）：
- 页面或commit信息明确提到 {cve_id}
- commit/PR属于 {package_name} 对应仓库
- 修改内容与漏洞描述相关（安全校验、边界检查、TLS校验、越界、空指针等）
- 上游公告/issue/PR/commit之间能形成对应关系

输出（严格JSON，仅此一个对象）：
{{
  "status": "found" or "not_found",
  "patch_url": "",
  "commit_hash": "",
  "reason": ""
}}

说明：
- patch_url 优先返回可直接下载的 .patch/.diff 链接
- 如果只有commit页面，也返回commit URL（后续程序会尝试构造patch链接）
""".strip()

def extract_json(text: str) -> dict:
    """尽量从模型输出中提取 JSON。"""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"Agent output is not valid JSON: {text[:500]}")
    return json.loads(m.group(0))

async def run_agent(issue_url: str, package_name: str, cve_id: str) -> dict:
    playwright_agent = await create_mcp_agent(
        local_config=config_path,
        task_updater=None
    )
    prompt = build_cve_patch_prompt(issue_url, package_name, cve_id)
    try:
        raw = await playwright_agent.astep(prompt)
        content = raw.msg.content if raw.msg else str(raw)
        data = extract_json(content)
        status = data.get("status", "").strip()

        if status != "found":
            return {
                "status": "not_found",
                "patch_url": "",
                "commit_hash": "",
                "reason": data.get("reason", "No reliable patch found"),
            }

        return {
            "status": "found",
            "patch_url": data.get("patch_url", "").strip(),
            "commit_hash": data.get("commit_hash", "").strip(),
            "reason": data.get("reason", "").strip(),
        }
    except Exception as exc:
        return {
            "status": "not_found",
            "patch_url": "",
            "commit_hash": "",
            "reason": f"Agent error: {exc}",
        }
    finally:
        await playwright_agent.disconnect()