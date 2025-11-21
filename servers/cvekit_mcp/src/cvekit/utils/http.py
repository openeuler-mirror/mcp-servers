import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def get_with_retry(
    url: str,
    *,
    max_retries: int = 3,
    timeout: int = 30,
    backoff_factor: float = 2.0,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> requests.Response:
    """
    封装带重试和日志的 requests.get 调用。

    - 对网络错误、超时等进行有限次数重试（指数退避）
    - 每次重试都会记录 warning 日志，最终失败记录 error 日志并抛出异常

    Args:
        url: 请求 URL
        max_retries: 最大重试次数
        timeout: 超时时间（秒）
        backoff_factor: 退避因子，下一次重试等待时间 = backoff_factor ** attempt
        headers: 额外请求头
        **kwargs: 透传给 requests.get 的其它参数

    Returns:
        requests.Response 实例（调用方负责调用 raise_for_status / json 等）

    Raises:
        requests.RequestException: 所有重试均失败时抛出最后一次的异常
    """
    merged_headers: Dict[str, str] = {}
    if headers:
        merged_headers.update(headers)

    last_exc: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            logger.debug(
                f"[get_with_retry] GET {url}, attempt {attempt + 1}/{max_retries}, timeout={timeout}"
            )
            resp = requests.get(url, headers=merged_headers, timeout=timeout, **kwargs)
            return resp
        except requests.RequestException as e:
            last_exc = e
            logger.warning(
                f"[get_with_retry] 请求失败 (尝试 {attempt + 1}/{max_retries}): {url}: {e}"
            )
            if attempt < max_retries - 1:
                # 指数退避
                sleep_secs = backoff_factor ** attempt
                time.sleep(sleep_secs)
            else:
                logger.error(
                    f"[get_with_retry] 所有重试均失败 ({max_retries} 次): {url}: {e}"
                )
                raise

    # 理论上不会到这里
    if last_exc:
        raise last_exc

