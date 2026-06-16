#!/usr/bin/env python3
"""
测试 Method._restore_modifiers() 函数
"""

import sys
sys.path.insert(0, '/home/dev/mcp-servers/servers/cvekit_mcp/src/cvekit/utils/mystique/src')

import pytest

from project import Method
from common import Language
from codefile import CodeFile

# 测试用例
test_cases = [
    {
        "name": "标准函数定义（无修饰符）",
        "raw_code": """static int epf_ntb_init(void)
{
    int ret;
    return 0;
}""",
        "function_name": "epf_ntb_init",
        "start_line": 1,
    },
    {
        "name": "带有 __init 修饰符的函数定义",
        "raw_code": """static int __init epf_ntb_init(void)
{
    int ret;
    return 0;
}""",
        "function_name": "epf_ntb_init",
        "start_line": 1,
    },
    {
        "name": "带有 __init 修饰符的函数定义（两个空格）",
        "raw_code": """static int  __init epf_ntb_init(void)
{
    int ret;
    return 0;
}""",
        "function_name": "epf_ntb_init",
        "start_line": 1,
    },
    {
        "name": "带有 __init 和其他修饰符的函数定义",
        "raw_code": """static int __init __maybe_unused epf_ntb_init(void)
{
    int ret;
    return 0;
}""",
        "function_name": "epf_ntb_init",
        "start_line": 1,
    },
    {
        "name": "带有 __exit 修饰符的函数定义",
        "raw_code": """static void __exit epf_ntb_exit(void)
{
    return;
}""",
        "function_name": "epf_ntb_exit",
        "start_line": 1,
    },
]

@pytest.mark.parametrize("test_case", test_cases, ids=lambda case: case["name"])
def test_restore_modifiers(test_case):
    print(f"\n{'='*80}")
    print(f"测试用例: {test_case['name']}")
    print(f"{'='*80}")
    print(f"raw_code:\n{test_case['raw_code']}")
    print(f"{'-'*80}")
    
    # 测试 _extract_function_signature_from_raw_code
    signature = Method._extract_function_signature_from_raw_code(
        test_case['raw_code'],
        test_case['function_name'],
        test_case['start_line']
    )
    
    print(f"提取的函数签名: {signature}")
    print(f"{'-'*80}")
    
    # 测试 _restore_init_exit_user_modifiers
    # 模拟 Tree-sitter 丢失 __init 的情况
    if "__init" in test_case['raw_code']:
        code = test_case['raw_code'].replace("__init ", "").replace("__init", "")
    elif "__exit" in test_case['raw_code']:
        code = test_case['raw_code'].replace("__exit ", "").replace("__exit", "")
    else:
        code = test_case['raw_code']
    
    print(f"模拟 Tree-sitter 丢失修饰符后的代码:\n{code}")
    print(f"{'-'*80}")
    
    restored_code = Method._restore_init_exit_user_modifiers(
        code,
        test_case['raw_code'],
        test_case['function_name'],
        test_case['start_line']
    )
    
    print(f"恢复后的代码:\n{restored_code}")
    print(f"{'-'*80}")
    
    # 检查是否恢复成功
    if "__init" in test_case['raw_code']:
        if "__init" in restored_code:
            print(f"✓ __init 修饰符恢复成功")
        else:
            print(f"✗ __init 修饰符恢复失败")
    
    if "__exit" in test_case['raw_code']:
        if "__exit" in restored_code:
            print(f"✓ __exit 修饰符恢复成功")
        else:
            print(f"✗ __exit 修饰符恢复失败")

if __name__ == "__main__":
    print(f"\n{'#'*80}")
    print(f"Method._restore_modifiers() 测试")
    print(f"{'#'*80}")

    for test_case in test_cases:
        test_restore_modifiers(test_case)

    print(f"\n{'#'*80}")
    print(f"测试完成")
    print(f"{'#'*80}")
