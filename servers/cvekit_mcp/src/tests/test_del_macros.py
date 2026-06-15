#!/usr/bin/env python3
"""
测试 del_macros() 函数是否删除 __init 修饰符
"""

import sys
sys.path.insert(0, '/home/dev/mcp-servers/servers/cvekit_mcp/src/cvekit/utils/mystique/src')

from format import del_macros

# 测试用例
test_cases = [
    {
        "name": "标准函数定义（无修饰符）",
        "code": """static int epf_ntb_init(void)
{
    int ret;
    return 0;
}"""
    },
    {
        "name": "带有 __init 修饰符的函数定义",
        "code": """static int __init epf_ntb_init(void)
{
    int ret;
    return 0;
}"""
    },
    {
        "name": "带有 __init 修饰符的函数定义（两个空格）",
        "code": """static int  __init epf_ntb_init(void)
{
    int ret;
    return 0;
}"""
    },
    {
        "name": "带有 __init 和其他修饰符的函数定义",
        "code": """static int __init __maybe_unused epf_ntb_init(void)
{
    int ret;
    return 0;
}"""
    },
    {
        "name": "带有 __exit 修饰符的函数定义",
        "code": """static void __exit epf_ntb_exit(void)
{
    return;
}"""
    },
]

def test_del_macros(code: str, test_name: str):
    print(f"\n{'='*80}")
    print(f"测试用例: {test_name}")
    print(f"{'='*80}")
    print(f"原始代码:\n{code}")
    print(f"{'-'*80}")
    
    # 调用 del_macros()
    result = del_macros(code)
    print(f"处理后代码:\n{result}")
    print(f"{'-'*80}")
    
    # 检查原始代码中是否包含 __init
    if '__init' in code:
        print(f"✓ 原始代码中包含 '__init' 修饰符")
    else:
        print(f"✗ 原始代码中不包含 '__init' 修饰符")
    
    # 检查处理后代码中是否包含 __init
    if '__init' in result:
        print(f"✓ 处理后代码中包含 '__init' 修饰符")
    else:
        print(f"✗ 处理后代码中不包含 '__init' 修饰符")
    
    # 检查原始代码中是否包含 __exit
    if '__exit' in code:
        print(f"✓ 原始代码中包含 '__exit' 修饰符")
    else:
        print(f"✗ 原始代码中不包含 '__exit' 修饰符")
    
    # 检查处理后代码中是否包含 __exit
    if '__exit' in result:
        print(f"✓ 处理后代码中包含 '__exit' 修饰符")
    else:
        print(f"✗ 处理后代码中不包含 '__exit' 修饰符")

# 运行所有测试用例
print(f"\n{'#'*80}")
print(f"del_macros() 函数测试")
print(f"{'#'*80}")

for test_case in test_cases:
    test_del_macros(test_case["code"], test_case["name"])

print(f"\n{'#'*80}")
print(f"测试完成")
print(f"{'#'*80}")
