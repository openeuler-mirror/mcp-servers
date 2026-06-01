"""
This file is based on the project "patch-backporting":
  https://github.com/OS3Lab/patch-backporting
The original code is licensed under the MIT License.
See third_party/patch-backporting/LICENSE for the full license text.

本文件在 OS3Lab/patch-backporting 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.

----

context window = input + output, gpt-4-turbo: 128k
In terms of characters, 3-4 characters of English are about one token. This can drop all the way to 0.4 characters per token in Chinese.

Reference
https://platform.openai.com/docs/models/gpt-4-turbo-and-gpt-4
https://community.openai.com/t/character-limit-response-for-the-gpt-3-5-api/426713/2
"""

import datetime
from urllib.parse import urlparse

import requests
from rich import print

price = {
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4-turbo-2024-04-09": (0.01, 0.03),
    "gpt-4-0125-preview": (0.01, 0.03),
    "gpt-4o-2024-05-13": (0.005, 0.015),
    "gpt-4o-2024-08-06": (0.0025, 0.01),
}


def _empty_usage():
    return {
        "current_time": datetime.datetime.now(),
        "total_cost": 0.0,
        "total_consume_input": 0,
        "total_consume_output": 0,
        "total_consume_tokens": 0,
    }


def _is_official_openai_base_url(base_url):
    if not base_url:
        return True
    parsed = urlparse(str(base_url).strip())
    return parsed.hostname == "api.openai.com"


def get_usage(api_key, provider="openai", base_url=None):
    """
    获取 API 使用量统计
    
    Args:
        api_key: API 密钥
        provider: 模型提供商，可选值: "openai", "deepseek"，默认为 "openai"
        base_url: LLM API 基础地址。仅官方 OpenAI 地址会查询 usage。
    
    Returns:
        dict: 包含使用量统计信息的字典
    """
    # 对于非 OpenAI 官方 usage API，返回默认的空使用量数据。
    # 注意：provider=openai 也可能只是表示 OpenAI-compatible 协议。
    provider = (provider or "").lower()
    if provider != "openai" or not _is_official_openai_base_url(base_url):
        return _empty_usage()
    if not api_key:
        return _empty_usage()
    
    # 仅对 OpenAI 提供商调用 API
    headers = {
        # 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.99 Safari/537.36',
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }

    # Get recent usage info
    start_date = (datetime.datetime.now() - datetime.timedelta(days=99)).strftime(
        "%Y-%m-%d"
    )
    end_date = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    data = (datetime.datetime.now()).strftime("%Y-%m-%d")
    try:
        resp_billing = requests.get(
            f"https://api.openai.com/v1/usage?date={data}",
            headers=headers,
            timeout=10,
        )
        if not resp_billing.ok:
            return _empty_usage()
        billing_data = resp_billing.json()
    except (requests.RequestException, ValueError):
        return _empty_usage()

    total_price = 0.0
    total_consume_input = 0
    total_consume_output = 0
    for item in billing_data["data"]:
        if item["snapshot_id"] in price:
            input_p, output_p = price[item["snapshot_id"]]
            total_consume_input += item["n_context_tokens_total"]
            total_price += item["n_context_tokens_total"] * input_p / 1000
            total_consume_output += item["n_generated_tokens_total"]
            total_price += item["n_generated_tokens_total"] * output_p / 1000
        else:
            print(f"Unknown model: {item['snapshot_id']}")
    result = {
        "current_time": datetime.datetime.now(),
        "total_cost": total_price,
        "total_consume_input": total_consume_input,
        "total_consume_output": total_consume_output,
        "total_consume_tokens": total_consume_input + total_consume_output,
    }

    return result


if __name__ == "__main__":
    import os

    usage = get_usage(os.getenv("OPENAI_API_KEY"))
    print(f"\nCurrent time: {usage['current_time']}")
    print(f"Total cost: ${usage['total_cost']:.2f}")
    print(
        f"Total consume input: {usage['total_consume_input']/1000}(k), output: {usage['total_consume_output']/1000}(k)"
    )
    print(f"Total consume tokens: {usage['total_consume_tokens']/1000}(k)\n")
