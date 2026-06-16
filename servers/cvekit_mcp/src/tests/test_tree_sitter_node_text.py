#!/usr/bin/env python3
"""
测试 Tree-sitter 的 node.text 是否包含 __init 修饰符
"""

import tree_sitter_c as tsc
import warnings
from tree_sitter import Language, Parser

# 加载 C 语言解析器
try:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="int argument support is deprecated",
            category=DeprecationWarning,
        )
        C_LANGUAGE = Language(tsc.language())
    print("✓ 成功加载 C 语言解析器")
except Exception as e:
    print(f"✗ 加载 C 语言解析器失败: {e}")
    exit(1)

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
]

def find_function_definitions(node):
    """递归查找所有函数定义节点"""
    if node.type == "function_definition":
        yield node
    for child in node.children:
        yield from find_function_definitions(child)

def parse_code(code: str, test_name: str):
    print(f"\n{'='*80}")
    print(f"测试用例: {test_name}")
    print(f"{'='*80}")
    print(f"原始代码:\n{code}")
    print(f"{'-'*80}")
    
    # 解析代码
    parser = Parser(C_LANGUAGE)
    tree = parser.parse(code.encode('utf-8'))
    root_node = tree.root_node
    
    print(f"✓ 解析成功")
    print(f"根节点类型: {root_node.type}")
    
    # 查找函数定义节点
    function_defs = list(find_function_definitions(root_node))
    print(f"\n✓ 查询到 {len(function_defs)} 个函数定义节点")
    
    for i, function_def_node in enumerate(function_defs):
        print(f"\n函数 #{i+1}:")
        print(f"  函数定义节点类型: {function_def_node.type}")
        
        # 提取 node.text
        function_def_text = function_def_node.text.decode('utf-8')
        print(f"  node.text:\n{function_def_text}")
        
        # 检查 node.text 中是否包含 __init
        if '__init' in function_def_text:
            print(f"  ✓ node.text 中包含 '__init' 修饰符")
            # 找到 __init 的位置
            init_pos = function_def_text.find('__init')
            print(f"  '__init' 位置: {init_pos}")
            # 显示 __init 周围的代码
            context_start = max(0, init_pos - 20)
            context_end = min(len(function_def_text), init_pos + 20)
            print(f"  '__init' 周围代码: ...{function_def_text[context_start:context_end]}...")
        else:
            print(f"  ✗ node.text 中不包含 '__init' 修饰符")
        
        # 检查原始代码中是否包含 __init
        if '__init' in code:
            print(f"  ✓ 原始代码中包含 '__init' 修饰符")
        else:
            print(f"  ✗ 原始代码中不包含 '__init' 修饰符")

# 运行所有测试用例
print(f"\n{'#'*80}")
print(f"Tree-sitter node.text 测试")
print(f"{'#'*80}")

for test_case in test_cases:
    parse_code(test_case["code"], test_case["name"])

print(f"\n{'#'*80}")
print(f"测试完成")
print(f"{'#'*80}")
