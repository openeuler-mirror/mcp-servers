import json
import os
import hashlib
from datetime import datetime
import logging
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.cve_analyzer_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
ISSUE_CACHE = os.path.join(CACHE_DIR, "issue_cache.json")
COMMITS_CACHE = os.path.join(CACHE_DIR, "COMMITS_CACHE.json")
BRANCHES_ANALYSIS_CACHE = os.path.join(CACHE_DIR, "branches_analysis_cache.json")


def _get_cache_key(*args) -> str:
    """生成缓存键"""
    key_str = "|".join(str(arg) for arg in args)
    return hashlib.md5(key_str.encode()).hexdigest()


def load_cache(cache_file: str, max_age_hours: int = 24) -> dict:
    """加载缓存文件，可设置最大缓存时间(小时)"""
    try:
        if not os.path.exists(cache_file):
            return {}
        
        with open(cache_file, "r") as f:
            data = json.load(f)
            
            # 检查缓存新鲜度
            now = datetime.now()
            for key in list(data.keys()):
                cache_time = datetime.fromisoformat(data[key]["timestamp"])
                if (now - cache_time).total_seconds() > max_age_hours * 3600:
                    del data[key]

            return data
    except Exception:
        return {}


def save_cache(cache_file: str, key: str, value: Any) -> None:
    """保存数据到缓存"""
    try:
        # 确保缓存目录存在
        cache_dir = os.path.dirname(cache_file)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        
        data = load_cache(cache_file)
        data[key] = {
            "data": value,
            "timestamp": datetime.now().isoformat(),
        }
        
        # 尝试序列化，确保数据可以转换为JSON
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error(f"缓存数据无法序列化为JSON: {str(e)}")
            raise
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"缓存已保存到: {cache_file}, key: {key}, 文件大小: {os.path.getsize(cache_file)} bytes")
    except Exception as e:
        logger.error(f"保存缓存失败: {cache_file}, key: {key}, 错误: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        # 不抛出异常，只记录错误，避免影响主流程

def delete_cache_key(cache_file: str, key: str) -> None:
    """删除指定缓存文件中的某个key"""
    try:
        if not os.path.exists(cache_file):
            logger.info(f"缓存文件不存在，无需删除key: {cache_file}")
            return
        
        # 加载现有缓存
        data = load_cache(cache_file)
        if key in data:
            del data[key]  # 删除目标key
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"已删除缓存key: {key}，缓存文件: {cache_file}")
        else:
            logger.info(f"缓存key不存在，无需删除: {key} (文件: {cache_file})")
    except Exception as e:
        logger.error(f"删除缓存key失败: {cache_file}, key: {key}, 错误: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

def get_cached_data(cache_file: str, key: str, max_age_hours: int = 24) -> Any:
    """获取缓存数据"""
    data = load_cache(cache_file, max_age_hours)
    return data.get(key, {}).get("data")


def cached(
    cache_file: str,
    key_builder: Optional[Callable[..., str]] = None,
    *,
    max_age_hours: int = 24,
    use_cache_kw: Optional[str] = "use_cache",
    load_transform: Optional[Callable[[Any], Any]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    通用缓存装饰器，统一缓存读写和异常处理逻辑。

    Args:
        cache_file: 缓存文件路径
        key_builder: 构造缓存 key 的函数，如果为空则使用函数名+参数自动生成
        max_age_hours: 缓存有效期（小时）
        use_cache_kw: 控制是否使用缓存的关键字参数名；为 None 表示忽略此开关
        load_transform: 从缓存读取数据后的转换函数（用于兼容旧缓存结构）
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            use_cache = True
            if use_cache_kw is not None:
                use_cache = kwargs.get(use_cache_kw, True)

            if not use_cache:
                return func(*args, **kwargs)

            # 生成 cache key
            if key_builder is not None:
                key = key_builder(*args, **kwargs)
            else:
                key = _get_cache_key(
                    func.__name__,
                    *args,
                    *[f"{k}={v}" for k, v in kwargs.items() if k != use_cache_kw],
                )

            # 读取缓存
            cached_value = get_cached_data(cache_file, key, max_age_hours)
            if cached_value is not None:
                if load_transform is not None:
                    try:
                        return load_transform(cached_value)
                    except Exception as e:  # 兼容旧缓存失败时，回退到正常流程
                        logger.warning(f"处理缓存数据失败，将忽略缓存重新计算: {e}")
                return cached_value

            # 缓存未命中，执行函数并写入缓存
            result = func(*args, **kwargs)
            if result is not None:
                try:
                    save_cache(cache_file, key, result)
                except Exception:
                    # 保存失败不影响正常返回
                    pass
            return result

        return wrapper

    return decorator