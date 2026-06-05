#!/usr/bin/env python3
"""
测试 recover_placeholder 函数的执行流程
使用测试文件 1.pre.c 和 2.post.c 来演示整个流程
"""

import sys
import os
sys.path.append('/home/liping/mystique/src')

from project import Method, File, Project
from common import Language
from codefile import CodeFile

def test_recover_placeholder():
    print("🚀 开始测试 recover_placeholder 函数执行流程")
    print("=" * 80)
    
    # 读取测试文件
    pre_file_path = "/home/liping/mystique/test_example/1.pre.c"
    post_file_path = "/home/liping/mystique/test_example/2.post.c"
    
    print(f"📁 读取测试文件:")
    print(f"  pre文件: {pre_file_path}")
    print(f"  post文件: {post_file_path}")
    
    with open(pre_file_path, "r") as f:
        pre_code = f.read()
    with open(post_file_path, "r") as f:
        post_code = f.read()
    
    print(f"  pre代码长度: {len(pre_code)} 字符")
    print(f"  post代码长度: {len(post_code)} 字符")
    print()
    
    # 创建项目和方法
    print(f"🏗️ 创建项目和方法:")
    pre_codefile = CodeFile(pre_file_path, pre_code)
    post_codefile = CodeFile(post_file_path, post_code)
    
    pre_project = Project("1.pre", [pre_codefile], Language.C)
    post_project = Project("2.post", [post_codefile], Language.C)
    
    # 获取方法
    pre_method = pre_project.get_only_method()
    post_method = post_project.get_only_method()
    
    # 设置对应关系
    pre_method.counterpart = post_method
    post_method.counterpart = pre_method
    
    print(f"📋 方法信息:")
    print(f"  pre_method.name: {pre_method.name}")
    print(f"  pre_method.start_line: {pre_method.start_line}")
    print(f"  pre_method.end_line: {pre_method.end_line}")
    print(f"  pre_method.rel_line_set: {sorted(pre_method.rel_line_set)}")
    print()
    
    # 模拟切片过程
    print(f"🔍 模拟切片过程:")
    # 假设切片结果包含第3行（差异行）
    slice_lines = {3}  # 相对行号，对应 strcpy 那一行
    print(f"  假设切片结果 slice_lines: {slice_lines}")
    print()
    
    # 模拟大模型修复后的代码（包含占位符）
    print(f"🔍 模拟大模型修复后的代码:")
    # 这里模拟一个包含占位符的代码
    placeholder = "PLACEHOLDER"
    fixed_code_with_placeholder = f"""int vulnerable_function(char *input) {{
    char buffer[100];
    {placeholder}
    printf("Input: %s\\n", buffer);
    return 0;
}}"""
    
    print(f"  fixed_code_with_placeholder:")
    for i, line in enumerate(fixed_code_with_placeholder.split("\n")):
        print(f"    {i+1}: {repr(line)}")
    print()
    
    # 调用 recover_placeholder 函数
    print(f"🔧 调用 recover_placeholder 函数:")
    print(f"  这将触发以下调用链:")
    print(f"    1. recover_placeholder(fixed_code, slice_lines, placeholder)")
    print(f"    2. -> reduced_hunks(slice_lines)")
    print(f"    3. -> code_hunks(placeholder_lines)")
    print(f"    4. -> 替换占位符为实际代码")
    print()
    
    # 调用函数（这会触发所有调试信息）
    result = pre_method.recover_placeholder(
        fixed_code_with_placeholder, 
        slice_lines, 
        placeholder
    )
    
    print(f"🎯 最终结果:")
    if result:
        print(f"  ✅ 恢复成功")
        print(f"  result 长度: {len(result)} 字符")
        print(f"  result 内容:")
        for i, line in enumerate(result.split("\n")):
            print(f"    {i+1}: {repr(line)}")
    else:
        print(f"  ❌ 恢复失败")
    print()
    
    print("✅ 测试完成！")
    print("=" * 80)

if __name__ == "__main__":
    test_recover_placeholder()
