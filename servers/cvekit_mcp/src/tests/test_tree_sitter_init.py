#!/usr/bin/env python3
"""
测试 Tree-sitter 能否正确解析带有 __init 修饰符的 C 代码
"""

import tree_sitter_c as tsc
from tree_sitter import Language, Parser

# 加载 C 语言解析器
try:
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
        "name": "带有 __init 修饰符的函数定义（多个空格）",
        "code": """static int   __init   epf_ntb_init(void)
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
    print(f"根节点文本: {root_node.text.decode('utf-8')[:100]}...")
    
    # 查找函数定义节点
    function_defs = list(find_function_definitions(root_node))
    print(f"\n✓ 查询到 {len(function_defs)} 个函数定义节点")
    
    for i, function_def_node in enumerate(function_defs):
        print(f"\n函数 #{i+1}:")
        print(f"  函数定义节点类型: {function_def_node.type}")
        function_def_text = function_def_node.text.decode('utf-8')
        print(f"  函数定义节点文本:\n{function_def_text}")
        
        # 检查函数定义节点中是否包含 __ __init
        if '__init' in function_def_text:
            print(f"  ✓ 函数定义节点中包含 '__init' 修饰符")
            # 找到 __init 的位置
            init_pos = function_def_text.find('__init')
            print(f"  '__init' 位置: {init_pos}")
            # 显示 __init 周围的代码
            context_start = max(0, init_pos - 20)
            context_end = min(len(function_def_text), init_pos + 20)
            print(f"  '__init' 周围代码: ...{function_def_text[context_start:context_end]}...")
        else:
            print(f"  ✗ 函数定义节点中不包含 '__init' 修饰符")
        
        # 遍历子节点
        print(f"  子节点:")
        def traverse_node(node, depth=0):
            indent = "  " * depth
            node_text = node.text.decode('utf-8')
            if len(node_text) > 50:
                node_text = node_text[:50] + "..."
            print(f"{indent}- {node.type}: {node_text}")
            for child in node.children:
                traverse_node(child, depth + 1)
        
        traverse_node(function_def_node, depth=1)

# 运行所有测试用例
print(f"\n{'#'*80}")
print(f"Tree-sitter C 语言解析器测试")
print(f"{'#'*80}")

for test_case in test_cases:
    parse_code(test_case["code"], test_case["name"])

print(f"\n{'#'*80}")
print(f"测试完成")
print(f"{'#'*80}")
