#!/usr/bin/env python3
"""
测试从 raw_code 中恢复 __init 修饰符的逻辑
"""

import re

def extract_function_signature_from_raw_code(raw_code: str, function_name: str, start_line: int) -> str | None:
    """
    从 raw_code 中提取函数签名
    
    Args:
        raw_code: 原始代码
        function_name: 函数名
        start_line: 函数起始行号（1-based）
    
    Returns:
        函数签名，如果找不到则返回 None
    """
    lines = raw_code.split("\n")
    
    # 从 start_line 开始向前查找函数签名
    # 函数签名可能在 start_line 之前（例如：static int __init epf_ntb_init(void)）
    # 也可能在 start_line 之前多行（例如：static int\n__init\nepf_ntb_init(void)）
    
    # 从 start_line - 1 开始向前查找（最多向前查找 5 行）
    for i in range(max(0, start_line - 6), start_line):
        line = lines[i].strip()
        
        # 检查是否包含函数名
        if function_name in line:
            # 提取函数签名（从行首到函数名）
            # 例如：static int __init epf_ntb_init(void)
            # 提取：static int __init epf_ntb_init
            
            # 找到函数名的位置
            function_name_pos = line.find(function_name)
            if function_name_pos == -1:
                continue
            
            # 提取函数签名
            signature = line[:function_name_pos + len(function_name)]
            
            # 如果行首是 {，说明函数签名在上一行
            if signature.startswith("{"):
                # 向上查找函数签名
                for j in range(i - 1, max(0, i - 6), -1):
                    prev_line = lines[j].strip()
                    if prev_line and not prev_line.startswith("#"):
                        signature = prev_line
                        break
            
            return signature
    
    return None

def restore_init_exit_modifiers(code: str, raw_code: str, function_name: str, start_line: int) -> str:
    """
    从 raw_code 中恢复 __init 和 __exit 修饰符
    
    Args:
        code: 当前代码（可能丢失 __init/__exit）
        raw_code: 原始代码（包含 __init/__exit）
        function_name: 函数名
        start_line: 函数起始行号（1-based）
    
    Returns:
        恢复后的代码
    """
    # 从 raw_code 中提取函数签名
    signature = extract_function_signature_from_raw_code(raw_code, function_name, start_line)
    if signature is None:
        logging.warning(f"无法从 raw_code 中提取函数签名: {function_name}")
        return code
    
    # 检查签名中是否包含 __init 或 __exit
    if "__init" not in signature and "__exit" not in signature:
        return code
    
    # 从 code 中提取当前函数签名
    code_lines = code.split("\n")
    if not code_lines:
        return code
    
    # 找到第一行（函数签名）
    current_signature = code_lines[0]
    
    # 检查当前签名中是否包含 __init 或 __exit
    if "__init" in current_signature or "__exit" in current_signature:
        return code
    
    # 恢复 __init 或 __exit 修饰符
    # 策略：从 raw_code 的签名中提取修饰符，添加到当前签名中
    
    # 提取修饰符
    modifiers = []
    if "__init" in signature:
        modifiers.append("__init")
    if "__exit" in signature:
        modifiers.append("__exit")
    
    # 在函数名之前插入修饰符
    # 例如：static int epf_ntb_init(void) -> static int __init epf_ntb_init(void)
    function_name_pos = current_signature.find(function_name)
    if function_name_pos == -1:
        return code
    
    # 在函数名之前插入修饰符
    restored_signature = current_signature[:function_name_pos] + " ".join(modifiers) + " " + current_signature[function_name_pos:]
    
    # 替换第一行
    code_lines[0] = restored_signature
    
    return "\n".join(code_lines)

# 测试用例
test_cases = [
    {
        "name": "标准函数定义（无修饰符）",
        "raw_code": """static int epf_ntb_init(void)
{
    int ret;
    return 0;
}""",
        "code": """static int epf_ntb_init(void)
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
        "code": """static int epf_ntb_init(void)
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
        "code": """static int  epf_ntb_init(void)
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
        "code": """__maybe_unused epf_ntb_init(void)
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
        "code": """static void epf_ntb_exit(void)
{
    return;
}""",
        "function_name": "epf_ntb_exit",
        "start_line": 1,
    },
]

def test_restore_init_exit_modifiers(test_case: dict):
    print(f"\n{'='*80}")
    print(f"测试用例: {test_case['name']}")
    print(f"{'='*80}")
    print(f"raw_code:\n{test_case['raw_code']}")
    print(f"{'-'*80}")
    print(f"code (可能丢失 __init/__exit):\n{test_case['code']}")
    print(f"{'-'*80}")
    
    # 恢复修饰符
    result = restore_init_exit_modifiers(
        test_case['code'],
        test_case['raw_code'],
        test_case['function_name'],
        test_case['start_line']
    )
    
    print(f"恢复后的代码:\n{result}")
    print(f"{'-'*80}")
    
    # 检查是否恢复成功
    if "__init" in test_case['raw_code']:
        if "__init" in result:
            print(f"✓ __init 修饰符恢复成功")
        else:
            print(f"✗ __init 修饰符恢复失败")
    
    if "__exit" in test_case['raw_code']:
        if "__exit" in result:
            print(f"✓ __exit 修饰符恢复成功")
        else:
            print(f"✗ __exit 修饰符恢复失败")

# 运行所有测试用例
print(f"\n{'#'*80}")
print(f"恢复 __init/__exit 修饰符测试")
print(f"{'#'*80}")

for test_case in test_cases:
    test_restore_init_exit_modifiers(test_case)

print(f"\n{'#'*80}")
print(f"测试完成")
print(f"{'#'*80}")
