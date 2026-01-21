import os
import logging

# 统一日志配置
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cve_webhook")


# 本地脚本路径 & Python 解释器 / 虚拟环境
APP_WORK_DIR = "/path/to/mcp-servers/servers/cvekit_mcp/src/cve_service"
APP_CLIENT_FILENAME = "app_client.py"
VENV_PYTHON = os.environ.get(
    "VENV_PYTHON",
    os.path.join(APP_WORK_DIR, ".venv", "bin", "python"),
)
# app_client 的日志输出文件，便于排查是否真正执行以及执行过程中的错误
APP_CLIENT_LOG = os.environ.get(
    "APP_CLIENT_LOG",
    os.path.join(APP_WORK_DIR, "app_client.log"),
)

# Gitee WebHook 密码（在 Gitee WebHook “密码”字段配置同样的值）
GITEE_WEBHOOK_TOKEN = os.environ.get("GITEE_WEBHOOK_TOKEN", "")

# GitCode WebHook 密码（在 GitCode WebHook “WebHook 密码”字段配置同样的值）
# 若不需要校验，可将该环境变量置空。
GITCODE_WEBHOOK_TOKEN = os.environ.get("GITCODE_WEBHOOK_TOKEN", "")

# GitCode OpenAPI 访问配置：用于在 GitCode Issue 下自动回复评论
GITCODE_ACCESS_TOKEN = os.environ.get("GITCODE_ACCESS_TOKEN", "")
GITCODE_API_BASE = os.environ.get("GITCODE_API_BASE", "https://api.gitcode.com/api/v5")

# 用于调用 Gitee OpenAPI 的访问令牌（需要具备对对应仓库 issue 评论的权限）
GITEE_ACCESS_TOKEN = os.environ.get("GITEE_ACCESS_TOKEN", "")
GITEE_API_BASE = os.environ.get("GITEE_API_BASE", "https://gitee.com/api/v5")

# 分支分析结果缓存文件，与 cvekit.utils.cache 中保持一致
BRANCHES_ANALYSIS_CACHE_FILE = os.path.expanduser("~/.cve_analyzer_cache/branches_analysis_cache.json")
