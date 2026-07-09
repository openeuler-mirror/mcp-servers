import threading
from typing import Dict, Any, Optional


# 任务结果存储（task_id -> result dict）
_migrate_results: Dict[str, Dict[str, Any]] = {}
_results_lock = threading.Lock()


def store_result(task_id: str, result: Dict[str, Any]):
    """存储任务结果供查询。"""
    with _results_lock:
        _migrate_results[task_id] = result
        if len(_migrate_results) > 1000:
            keys = list(_migrate_results.keys())[:-500]
            for k in keys:
                _migrate_results.pop(k, None)


def get_task_result(task_id: str) -> Optional[Dict[str, Any]]:
    """根据 task_id 查询任务结果。"""
    with _results_lock:
        return _migrate_results.get(task_id)
