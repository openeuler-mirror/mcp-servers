"""
统一的环境变量加载模块

此模块用于加载 src 目录下的 .env 文件，
所有需要使用环境变量的模块只需导入此模块即可自动加载环境变量。

使用方式：
    from cvekit.utils.env_loader import get_gitee_token, get_api_key
    
    token = get_gitee_token()
    api_key = get_api_key()
    
或者直接使用 os.getenv：
    import os
    token = os.getenv('GITEE_TOKEN')
"""
import os
from pathlib import Path
from dotenv import load_dotenv

SRC_DIR = Path(__file__).parent.parent.parent.absolute()
ENV_PATH = SRC_DIR / "cve_service"/ '.env'

# 加载环境变量（override=True 确保覆盖系统环境变量）
load_dotenv(ENV_PATH, override=True)


def get_gitee_token() -> str:
    """获取 Gitee Token"""
    return os.getenv('GITEE_TOKEN', '')


def get_api_key() -> str:
    """获取 API Key，优先使用 SiliconFlow"""
    return os.getenv('SILICONFLOW_API_KEY') or os.getenv('API_KEY') or os.getenv('OPENAI_KEY', '')


def get_llm_provider() -> str:
    """获取 LLM Provider"""
    return os.getenv('LLM_PROVIDER', 'siliconflow')


def get_default_clone_dir() -> str:
    """获取默认克隆目录"""
    return os.getenv('DEFAULT_CLONE_DIR', '')


def get_default_repo_url() -> str:
    """获取默认仓库 URL"""
    return os.getenv('DEFAULT_REPO_URL', '')


def get_default_fork_repo() -> str:
    """获取默认 Fork 仓库"""
    return os.getenv('DEFAULT_FORK_REPO', '')


def get_rpmbuild_path() -> str:
    """获取 rpmbuild 目录"""
    return os.getenv('RPMBUILD_PATH', os.path.expanduser('~/rpmbuild'))


def get_default_branches() -> str:
    """获取默认分支列表"""
    return os.getenv('DEFAULT_BRANCHES', '')


def get_env(key: str, default: str = '') -> str:
    """通用的环境变量获取函数"""
    return os.getenv(key, default)