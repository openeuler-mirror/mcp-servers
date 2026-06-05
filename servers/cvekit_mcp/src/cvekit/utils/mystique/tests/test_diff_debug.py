#!/usr/bin/env python3
"""
测试 diff_lines 获取过程的调试脚本
使用测试文件 1.pre.c 和 2.post.c 来演示整个流程
"""

import sys
import os
sys.path.append('/home/liping/mystique/src')

from project import Method, File, Project
from common import Language
from codefile import CodeFile

def test_diff_lines_debug():
    print("🚀 开始测试 diff_lines 获取过程")
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
    
    print(f"  pre项目创建完成")
    print(f"  post项目创建完成")
    print()
    
    # 获取方法
    pre_method = pre_project.get_only_method()
    post_method = post_project.get_only_method()
    
    print(f"📋 方法信息:")
    print(f"  pre_method.name: {pre_method.name}")
    print(f"  pre_method.start_line: {pre_method.start_line}")
    print(f"  pre_method.end_line: {pre_method.end_line}")
    print(f"  post_method.name: {post_method.name}")
    print(f"  post_method.start_line: {post_method.start_line}")
    print(f"  post_method.end_line: {post_method.end_line}")
    print()
    
    # 设置对应关系
    print(f"🔗 设置方法对应关系:")
    pre_method.counterpart = post_method
    post_method.counterpart = pre_method
    print(f"  ✅ 对应关系设置完成")
    print()
    
    # 测试 diff_lines 获取过程
    print(f"🔍 开始测试 diff_lines 获取过程:")
    print(f"  这将触发以下调用链:")
    print(f"    1. pre_method.diff_lines")
    print(f"    2. -> pre_method.patch_hunks")
    print(f"    3. -> get_patch_hunks(pre_code, post_code)")
    print(f"    4. -> 各种差异分析函数")
    print()
    
    # 获取 diff_lines (这会触发所有调试信息)
    diff_lines = pre_method.diff_lines
    
    print(f"🎯 最终结果:")
    print(f"  diff_lines: {sorted(diff_lines)}")
    print()
    
    # 测试 rel_diff_lines
    print(f"🔍 测试 rel_diff_lines 获取:")
    rel_diff_lines = pre_method.rel_diff_lines
    print(f"  rel_diff_lines: {sorted(rel_diff_lines)}")
    print()
    
    print("✅ 测试完成！")
    print("=" * 80)

if __name__ == "__main__":
    test_diff_lines_debug()
