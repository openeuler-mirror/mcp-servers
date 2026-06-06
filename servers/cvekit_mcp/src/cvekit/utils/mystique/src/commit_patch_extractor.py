#!/usr/bin/env python3
"""
This file is based on the project "Mystique":
  https://github.com/Mystique-OpenSource/mystique-opensource.github.io
The original code is licensed under the GNU General Public License v3.0.
See third_party/mystique/LICENSE for the full license text.

本文件在 Mystique-OpenSource/mystique 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.
"""


"""
从Linux仓库的commit ID提取补丁信息，并生成mystique工具所需的输入文件。

功能：
1. 从Linux commit获取patch
2. 解析patch找到修改的文件和方法
3. 在openEuler分支找到对应文件（支持文件名映射）
4. 提取方法级别的代码
5. 生成main.py需要的三个文件（pre/post/target）
"""

import argparse
import os
import re
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

# 导入Language枚举（用于文件扩展名检测）
# 不再需要AST解析器，因为我们只生成完整文件
try:
    from common import Language
except ImportError:
    # 如果无法导入，定义一个简单的Language枚举
    from enum import Enum
    class Language(Enum):
        C = 0
        JAVA = 1
        CPP = 2

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CommitPatchExtractor:
    """从Linux commit提取补丁信息并生成mystique输入文件"""
    
    def __init__(self, linux_repo_path: str, openeuler_repo_path: str, 
                 openeuler_branch: str, output_dir: str = "output"):
        """
        Args:
            linux_repo_path: Linux仓库的本地路径或URL
            openeuler_repo_path: openEuler仓库的本地路径或URL
            openeuler_branch: openEuler的目标分支
            output_dir: 输出目录
        """
        self.linux_repo_path = linux_repo_path
        self.openeuler_repo_path = openeuler_repo_path
        self.openeuler_branch = openeuler_branch
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件名映射规则（Linux -> openEuler）
        # 可以通过配置文件或自动检测
        self.file_mapping: Dict[str, str] = {}
        
    def get_commit_patch(self, commit_id: str) -> str:
        """从Linux仓库获取commit的patch"""
        logger.info(f"获取commit {commit_id} 的patch...")
        
        # 检查是本地路径还是URL
        if os.path.exists(self.linux_repo_path):
            repo_path = self.linux_repo_path
            cmd = ["git", "-C", repo_path, "show", commit_id, "--format=%H%n%P%n%s"]
        else:
            # 如果是URL，需要先clone或fetch
            logger.warning(f"Linux仓库路径不存在: {self.linux_repo_path}")
            logger.info("尝试从远程获取...")
            # 这里可以实现从远程获取的逻辑
            raise NotImplementedError("远程仓库访问需要实现git clone/fetch逻辑")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            # 获取格式化的patch
            patch_result = subprocess.run(
                ["git", "-C", repo_path, "show", commit_id],
                capture_output=True,
                text=True,
                check=True
            )
            return patch_result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"获取commit patch失败: {e}")
            raise
    
    def parse_patch_files(self, patch: str) -> List[Dict]:
        """
        解析patch，提取修改的文件列表
        
        Returns:
            List of dict with keys: 'old_path', 'new_path', 'hunks'
        """
        logger.info("解析patch文件...")
        files = []
        current_file = None
        
        lines = patch.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # 匹配文件路径变更
            if line.startswith('diff --git'):
                # 提取旧路径和新路径
                match = re.match(r'diff --git a/(.+?) b/(.+?)$', line)
                if match:
                    old_path = match.group(1)
                    new_path = match.group(2)
                    
                    # 查找文件模式（C文件、Java文件等）
                    if old_path.endswith(('.c', '.h', '.java')) or new_path.endswith(('.c', '.h', '.java')):
                        current_file = {
                            'old_path': old_path,
                            'new_path': new_path,
                            'hunks': []
                        }
                        files.append(current_file)
            
            # 解析hunk信息
            elif current_file and line.startswith('@@'):
                # @@ -start,count +start,count @@
                hunk_match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if hunk_match:
                    old_start = int(hunk_match.group(1))
                    old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 0
                    new_start = int(hunk_match.group(3))
                    new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 0
                    
                    current_file['hunks'].append({
                        'old_start': old_start,
                        'old_count': old_count,
                        'new_start': new_start,
                        'new_count': new_count
                    })
            
            i += 1
        
        logger.info(f"找到 {len(files)} 个修改的文件")
        return files
    
    def map_file_path(self, linux_path: str) -> Optional[str]:
        """
        将Linux文件路径映射到openEuler路径
        
        可以实现：
        1. 直接同名映射
        2. 配置文件映射
        3. 自动查找相似文件名
        """
        # 如果已经有映射，直接返回
        if linux_path in self.file_mapping:
            return self.file_mapping[linux_path]
        
        # 默认：尝试在openEuler仓库中查找同名文件
        # 这里可以实现更复杂的查找逻辑
        # 例如：在kernel目录下查找、处理重命名等
        
        # 简单实现：假设路径相同
        return linux_path
    
    def get_file_content_at_commit(self, repo_path: str, file_path: str, 
                                   commit_id: Optional[str] = None) -> Optional[str]:
        """获取指定commit的文件内容"""
        if commit_id:
            cmd = ["git", "-C", repo_path, "show", f"{commit_id}:{file_path}"]
        else:
            # 获取当前分支的文件
            cmd = ["git", "-C", repo_path, "show", f"HEAD:{file_path}"]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError:
            logger.warning(f"无法获取文件内容: {repo_path}:{file_path} at {commit_id}")
            return None
    
    def extract_function_from_code(self, code: str, file_path: str, 
                                  line_start: int, line_end: int) -> Optional[str]:
        """
        从代码中提取指定行范围对应的函数
        
        这是一个简化的实现，实际需要：
        1. 使用AST解析找到函数边界
        2. 处理嵌套函数
        3. 包含必要的头文件和上下文
        """
        lines = code.split('\n')
        if line_start < 1 or line_end > len(lines):
            return None
        
        # 简化为提取指定行范围
        # 实际应该找到完整的函数定义
        function_lines = lines[line_start - 1:line_end]
        
        # TODO: 使用ast_parser或类似工具找到完整函数
        # 这里先返回简单实现
        return '\n'.join(function_lines)
    
    def find_function_at_lines(self, code: str, target_line: int, language: Language = Language.C) -> Optional[Tuple[str, int, int]]:
        """
        找到包含指定行的函数（使用AST解析器）
        
        Returns:
            (function_code, start_line, end_line) or None
        """
        try:
            # 使用mystique的ASTParser
            ast = ASTParser(code, language)
            
            # C语言：查找函数定义
            if language == Language.C:
                query = "(function_definition)@func"
            else:  # Java
                query = "(method_declaration)@method"
            
            # 查找所有函数节点
            nodes = ast.query_all(query)
            
            for node in nodes:
                start_line = node.start_point[0] + 1  # tree-sitter行号从0开始
                end_line = node.end_point[0] + 1
                
                # 检查目标行是否在这个函数内
                if start_line <= target_line <= end_line:
                    # 提取函数代码
                    function_code = code[node.start_byte:node.end_byte]
                    return (function_code, start_line, end_line)
            
            logger.warning(f"未找到包含行 {target_line} 的函数")
            return None
            
        except Exception as e:
            logger.error(f"AST解析失败: {e}")
            # 降级到简单实现
            return self._find_function_simple(code, target_line)
    
    def _find_function_simple(self, code: str, target_line: int) -> Optional[Tuple[str, int, int]]:
        """简单的函数查找实现（备用方案）"""
        lines = code.split('\n')
        
        # 向上查找函数定义
        function_start = None
        for i in range(target_line - 1, -1, -1):
            line = lines[i]
            if re.search(r'\w+\s*\([^)]*\)\s*\{', line) or re.search(r'^\s*\w+\s+.*\(.*\)\s*\{', line):
                function_start = i
                break
        
        if function_start is None:
            return None
        
        # 找到函数结束
        brace_count = 0
        function_end = len(lines)
        
        for i in range(function_start, len(lines)):
            line = lines[i]
            brace_count += line.count('{') - line.count('}')
            if brace_count == 0 and i > function_start:
                function_end = i + 1
                break
        
        function_code = '\n'.join(lines[function_start:function_end])
        return (function_code, function_start + 1, function_end)
    
    def detect_language(self, file_path: str) -> Language:
        """根据文件扩展名检测语言"""
        if file_path.endswith('.java'):
            return Language.JAVA
        elif file_path.endswith(('.c', '.h')):
            return Language.C
        else:
            # 默认C语言
            return Language.C
    
    def generate_mystique_input(self, commit_id: str, 
                               linux_path: str, openeuler_path: str) -> Optional[Dict[str, str]]:
        """
        生成mystique main.py需要的三个完整文件（pre/post/target）
        
        不需要提取函数，直接生成完整的文件，让mystique自己处理函数提取
        
        Returns:
            Dict with keys: 'pre_file', 'post_file', 'target_file', 'linux_path', 'openeuler_path'
        """
        logger.info(f"生成mystique输入文件: {linux_path} -> {openeuler_path}")
        
        # 检测语言
        language = self.detect_language(linux_path)
        file_ext = '.java' if language == Language.JAVA else '.c'
        
        # 获取Linux commit前后的文件内容
        parent_commit = f"{commit_id}^"
        
        # Linux: 补丁前的文件（完整文件）
        linux_pre_content = self.get_file_content_at_commit(
            self.linux_repo_path, linux_path, parent_commit
        )
        # Linux: 补丁后的文件（完整文件）
        linux_post_content = self.get_file_content_at_commit(
            self.linux_repo_path, linux_path, commit_id
        )
        
        # openEuler: 目标文件（切换到指定分支）
        try:
            # 先切换到指定分支
            subprocess.run(
                ["git", "-C", self.openeuler_repo_path, "checkout", self.openeuler_branch],
                capture_output=True,
                check=True
            )
        except subprocess.CalledProcessError:
            logger.warning(f"无法切换到分支 {self.openeuler_branch}，使用当前分支")
        
        # openEuler: 目标文件（完整文件）
        openeuler_target_content = self.get_file_content_at_commit(
            self.openeuler_repo_path, openeuler_path, None
        )
        
        if not all([linux_pre_content, linux_post_content, openeuler_target_content]):
            logger.error("无法获取所有必要的文件内容")
            logger.error(f"  linux_pre: {linux_pre_content is not None}")
            logger.error(f"  linux_post: {linux_post_content is not None}")
            logger.error(f"  openeuler_target: {openeuler_target_content is not None}")
            if not linux_pre_content:
                logger.error(f"  无法获取Linux补丁前文件: {linux_path} at {parent_commit}")
            if not linux_post_content:
                logger.error(f"  无法获取Linux补丁后文件: {linux_path} at {commit_id}")
            if not openeuler_target_content:
                logger.error(f"  无法获取openEuler目标文件: {openeuler_path}")
            return None
        
        # 生成输出文件（直接使用完整文件）
        safe_commit_id = commit_id[:8].replace('/', '_')
        safe_file_path = linux_path.replace('/', '_').replace('.', '_')
        output_subdir = self.output_dir / f"{safe_commit_id}" / safe_file_path
        output_subdir.mkdir(parents=True, exist_ok=True)
        
        pre_file = output_subdir / f"1.pre{file_ext}"
        post_file = output_subdir / f"2.post{file_ext}"
        target_file = output_subdir / f"3.target{file_ext}"
        
        with open(pre_file, 'w') as f:
            f.write(linux_pre_content)
        with open(post_file, 'w') as f:
            f.write(linux_post_content)
        with open(target_file, 'w') as f:
            f.write(openeuler_target_content)
        
        logger.info(f"✅ 生成文件成功:")
        logger.info(f"   PRE文件: {pre_file}")
        logger.info(f"   POST文件: {post_file}")
        logger.info(f"   TARGET文件: {target_file}")
        
        result = {
            'pre_file': str(pre_file),
            'post_file': str(post_file),
            'target_file': str(target_file),
            'linux_path': linux_path,
            'openeuler_path': openeuler_path,
            'commit_id': commit_id
        }
        
        return result
    
    def find_target_function(self, target_code: str, target_path: str, 
                            source_func_code: str, language: Language = Language.C) -> Optional[str]:
        """在target代码中查找对应的函数（使用AST解析器）"""
        try:
            # 从source函数提取函数名
            func_name = self.extract_function_name(source_func_code)
            if not func_name:
                return None
            
            # 使用AST解析器查找函数
            ast = ASTParser(target_code, language)
            
            # C语言：查找函数定义
            if language == Language.C:
                query = "(function_definition declarator: (function_declarator declarator: (identifier) @func_name))@func"
            else:  # Java
                query = "(method_declaration name: (identifier) @func_name)@method"
            
            # 查找所有函数节点
            nodes = ast.query_all(query)
            
            for node in nodes:
                # 提取函数名（重新查询以获取capture name）
                func_name_query = "(function_definition declarator: (function_declarator declarator: (identifier) @func_name))" if language == Language.C else "(method_declaration name: (identifier) @func_name)"
                func_name_captures = ast.query(func_name_query, node=node)
                func_name_nodes = func_name_captures.get("@func_name", [])
                if not func_name_nodes:
                    continue
                
                found_func_name = target_code[func_name_nodes[0].start_byte:func_name_nodes[0].end_byte]
                
                if found_func_name == func_name:
                    # 找到匹配的函数，提取完整代码
                    function_code = target_code[node.start_byte:node.end_byte]
                    return function_code
            
            logger.warning(f"未在target文件中找到函数: {func_name}")
            return None
            
        except Exception as e:
            logger.error(f"AST解析失败: {e}")
            # 降级到简单实现
            func_name = self.extract_function_name(source_func_code)
            if not func_name:
                return None
            
            lines = target_code.split('\n')
            for i, line in enumerate(lines):
                if func_name in line and '(' in line:
                    func_info = self.find_function_at_lines(target_code, i + 1, language)
                    if func_info:
                        return func_info[0]
            
            return None
    
    def extract_function_name(self, func_code: str) -> Optional[str]:
        """从函数代码中提取函数名"""
        # 匹配函数定义模式
        match = re.search(r'\b(\w+)\s*\(', func_code)
        if match:
            return match.group(1)
        
        # 匹配类型 函数名 模式
        match = re.search(r'(\w+)\s+(\w+)\s*\(', func_code)
        if match:
            return match.group(2)
        
        return None


def main():
    parser = argparse.ArgumentParser(
        description="从Linux commit ID生成mystique工具输入文件"
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="Linux仓库的commit ID"
    )
    parser.add_argument(
        "--linux-repo",
        required=True,
        help="Linux仓库路径（本地路径或URL）"
    )
    parser.add_argument(
        "--openeuler-repo",
        required=True,
        help="openEuler仓库路径（本地路径或URL）"
    )
    parser.add_argument(
        "--openeuler-branch",
        required=True,
        help="openEuler目标分支"
    )
    parser.add_argument(
        "--output",
        default="output",
        help="输出目录（默认: output）"
    )
    parser.add_argument(
        "--file",
        help="指定处理的文件路径（可选，默认处理所有修改的文件）"
    )
    parser.add_argument(
        "--function",
        help="指定处理的函数名（已废弃，不再需要）",
        default=None
    )
    
    args = parser.parse_args()
    
    extractor = CommitPatchExtractor(
        linux_repo_path=args.linux_repo,
        openeuler_repo_path=args.openeuler_repo,
        openeuler_branch=args.openeuler_branch,
        output_dir=args.output
    )
    
    # 如果需要处理特定文件，先检查文件映射
    if args.file:
        openeuler_file = extractor.map_file_path(args.file)
        if not openeuler_file:
            logger.error(f"无法映射文件路径: {args.file}")
            logger.info(f"尝试在openEuler仓库中直接查找同名文件: {args.file}")
            # 尝试直接使用相同的路径
            openeuler_file = args.file
        
        result = extractor.generate_mystique_input(
            args.commit,
            args.file,
            openeuler_file
        )
        
        if result:
            logger.info("=" * 80)
            logger.info("✅ 生成mystique输入文件成功！")
            logger.info(f"📁 文件映射: {result['linux_path']} -> {result['openeuler_path']}")
            logger.info(f"")
            logger.info(f"使用方法：")
            logger.info(f"python3 src/main.py --pre {result['pre_file']} --post {result['post_file']} --target {result['target_file']}")
            logger.info("=" * 80)
        else:
            logger.error("❌ 生成文件失败")
    else:
        # 处理所有修改的文件
        patch = extractor.get_commit_patch(args.commit)
        files = extractor.parse_patch_files(patch)
        
        logger.info(f"发现 {len(files)} 个修改的文件")
        results = []
        
        for file_info in files:
            linux_path = file_info['new_path']
            openeuler_path = extractor.map_file_path(linux_path)
            
            if not openeuler_path:
                logger.warning(f"⚠️ 跳过无法映射的文件: {linux_path}，尝试使用相同路径")
                # 尝试直接使用相同的路径
                openeuler_path = linux_path
            
            logger.info(f"处理文件: {linux_path} -> {openeuler_path}")
            result = extractor.generate_mystique_input(
                args.commit,
                linux_path,
                openeuler_path
            )
            
            if result:
                results.append(result)
                logger.info(f"  ✅ 成功生成")
            else:
                logger.warning(f"  ❌ 生成失败")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"✅ 成功生成 {len(results)} 个mystique输入文件集")
        logger.info("=" * 80)
        
        for i, result in enumerate(results, 1):
            logger.info(f"\n{i}. {result['linux_path']} -> {result['openeuler_path']}")
            logger.info(f"   python3 src/main.py --pre {result['pre_file']} --post {result['post_file']} --target {result['target_file']}")


if __name__ == "__main__":
    main()

