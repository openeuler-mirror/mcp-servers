import json
import os
import hashlib
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.cve_analyzer_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
ISSUE_CACHE = os.path.join(CACHE_DIR, "issue_cache.json")
COMMITS_CACHE = os.path.join(CACHE_DIR, "COMMITS_CACHE.json")


def _get_cache_key(*args):
    """生成缓存键"""
    key_str = "|".join(str(arg) for arg in args)
    return hashlib.md5(key_str.encode()).hexdigest()

def load_cache(cache_file, max_age_hours=24):
    """加载缓存文件，可设置最大缓存时间(小时)"""
    try:
        if not os.path.exists(cache_file):
            return {}
        
        with open(cache_file, 'r') as f:
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

def save_cache(cache_file, key, value):
    """保存数据到缓存"""
    try:
        data = load_cache(cache_file)
        data[key] = {
            "data": value,
            "timestamp": datetime.now().isoformat()
        }
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"保存缓存失败: {str(e)}")

def get_cached_data(cache_file, key, max_age_hours=24):
    """获取缓存数据"""
    data = load_cache(cache_file, max_age_hours)
    return data.get(key, {}).get("data")