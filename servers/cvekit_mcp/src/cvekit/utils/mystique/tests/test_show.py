#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')

import ast_parser
from common import Language

pre_code = open('cache/7b91797feb/pre/code/3.target.c').read()
post_code = open('cache/7b91797feb/post/code/3.target.c').read()

pre_parser = ast_parser.ASTParser(pre_code, Language.C)
post_parser = ast_parser.ASTParser(post_code, Language.C)

# 查找所有 TS_C_METHOD
pre_methods = list(pre_parser.query_all(ast_parser.TS_C_METHOD))
post_methods = list(post_parser.query_all(ast_parser.TS_C_METHOD))

# 查找所有 TS_C_FUNC_DECL
pre_funcs = list(pre_parser.query_all(ast_parser.TS_C_FUNC_DECL))
post_funcs = list(post_parser.query_all(ast_parser.TS_C_FUNC_DECL))

print(f"Pre TS_C_METHOD: {len(pre_methods)}, TS_C_FUNC_DECL: {len(pre_funcs)}")
print(f"Post TS_C_METHOD: {len(post_methods)}, TS_C_FUNC_DECL: {len(post_funcs)}")

# 提取方法名
def extract_method_name(node):
    declarator = node.child_by_field_name('declarator')
    if declarator:
        for child in declarator.children:
            if child.type == 'identifier':
                return child.text.decode() if child.text else None
    return None

# 收集 pre 中的所有方法名
pre_names = set()
for m in pre_methods:
    name = extract_method_name(m)
    if name:
        pre_names.add(name)
for f in pre_funcs:
    name = extract_method_name(f)
    if name:
        pre_names.add(name)

# 收集 post 中的所有方法名
post_names = set()
for m in post_methods:
    name = extract_method_name(m)
    if name:
        post_names.add(name)
for f in post_funcs:
    name = extract_method_name(f)
    if name:
        post_names.add(name)

# 差异
added = post_names - pre_names
deleted = pre_names - post_names
common = pre_names & post_names

print(f"\nPre total methods: {len(pre_names)}")
print(f"Post total methods: {len(post_names)}")
print(f"Added: {len(added)}, Deleted: {len(deleted)}, Common: {len(common)}")

print("\n=== Added methods with 'show' ===")
for name in sorted(added):
    if 'show' in name.lower():
        print(f"  ADDED: {name}")

print("\n=== Deleted methods with 'show' ===")
for name in sorted(deleted):
    if 'show' in name.lower():
        print(f"  DELETED: {name}")

# 特别检查 show（不带其他字符）
print("\n=== Checking 'show' exactly ===")
print(f"  'show' in pre_names: {'show' in pre_names}")
print(f"  'show' in post_names: {'show' in post_names}")
print(f"  'show' in added: {'show' in added}")
