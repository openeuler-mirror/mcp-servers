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


from __future__ import annotations

import ast
import logging
import os
import sys
from collections import deque
from functools import cached_property

import networkx as nx
from tree_sitter import Node

import ast_parser
import config
import format
import joern
import utils
from ast_parser import ASTParser
from codefile import CodeFile
from common import Language
from difftools import AddHunk, DelHunk, Hunk, ModHunk, get_patch_hunks
from joern import PDGNode


class ProjectJoern:
    def __init__(self, cpg_dir: str, pdg_dir: str):
        self.cpg = joern.CPG(cpg_dir)
        self.pdgs: dict[tuple[int, str, str], joern.PDG] = self.build_pdgs(pdg_dir)
        self.pdgs_by_name_file: dict[tuple[str, str], list[tuple[int, joern.PDG]]] = {}
        for (line, name, file_path), pdg in self.pdgs.items():
            key = (name, file_path)
            self.pdgs_by_name_file.setdefault(key, []).append((line, pdg))
        for key in self.pdgs_by_name_file:
            self.pdgs_by_name_file[key].sort(key=lambda x: x[0])

    def build_pdgs(self, pdg_dir: str):
        dot_names = os.listdir(pdg_dir)
        pdgs: dict[tuple[int, str, str], joern.PDG] = {}
        for dot in dot_names:
            dot_path = os.path.join(pdg_dir, dot)
            try:
                pdg = joern.PDG(pdg_path=dot_path)
            except Exception as e:
                logging.warning(f"❌ PDG 加载失败: {dot_path}, {e}")
                continue
            if pdg.name is None:
                logging.warning(f"❌ PDG METHOD NODE NAME 为空: {dot_path}")
                continue
            if pdg.line_number is None or pdg.filename is None:
                continue
            pdgs[(pdg.line_number, pdg.name, pdg.filename)] = pdg
        return pdgs

    def get_pdg(self, method: Method) -> joern.PDG | None:
        exact = self.pdgs.get((method.start_line, method.name, method.file.path))
        if exact is not None:
            return exact

        # 回退：同名同文件按行号最近匹配，避免因预处理/格式化造成的行号轻微漂移
        candidates = self.pdgs_by_name_file.get((method.name, method.file.path), [])
        if not candidates:
            return None
        nearest_line, nearest_pdg = min(candidates, key=lambda x: abs(x[0] - method.start_line))
        if abs(nearest_line - method.start_line) > 120:
            logging.warning(
                "⚠️ PDG回退匹配跨度过大，跳过: method=%s file=%s start=%s nearest=%s",
                method.name,
                method.file.path,
                method.start_line,
                nearest_line,
            )
            return None
        logging.info(
            "ℹ️ PDG回退匹配: method=%s file=%s start=%s -> pdg_line=%s",
            method.name,
            method.file.path,
            method.start_line,
            nearest_line,
        )
        return nearest_pdg


class Project:
    def __init__(self, project_name: str, files: list[CodeFile], language: Language):
        self.project_name = project_name
        self.language = language
        self.files: list[File] = []

        self.files_path_set: set[str] = set()
        self.imports_signature_set: set[str] = set()
        self.classes_signature_set: set[str] = set()
        self.methods_signature_set: set[str] = set()
        self.fields_signature_set: set[str] = set()

        for file in files:
            # Use formated_code (same as create_code_tree) so tree-sitter
            # line numbers match Joern PDG line numbers.
            file = File(file.file_path, file.formated_code, self, language, raw_code=file.code)
            self.files.append(file)
            self.files_path_set.add(file.path)
            if language == Language.JAVA:
                self.imports_signature_set.update([import_.signature for import_ in file.imports])
                self.classes_signature_set.update([clazz.fullname for clazz in file.classes])
                self.methods_signature_set.update(
                    [method.signature for clazz in file.classes for method in clazz.methods])
                self.fields_signature_set.update([field.signature for clazz in file.classes for field in clazz.fields])
            elif language == Language.C:
                self.imports_signature_set.update([import_.signature for import_ in file.imports])
                self.methods_signature_set.update([method.signature for method in file.methods])

        self.joern: ProjectJoern | None = None

    def load_joern_graph(self, cpg_dir: str, pdg_dir: str):
        self.joern = ProjectJoern(cpg_dir, pdg_dir)

    def get_file(self, path: str) -> File | None:
        for file in self.files:
            if file.path == path:
                return file
        return None

    def get_import(self, signature: str) -> Import | None:
        for file in self.files:
            for import_ in file.imports:
                if import_.signature == signature:
                    return import_
        return None

    def get_class(self, fullname: str) -> Class | None:
        for file in self.files:
            for clazz in file.classes:
                if clazz.fullname == fullname:
                    return clazz
        return None

    def get_method(self, fullname: str) -> Method | None:
        if self.language == Language.JAVA:
            for file in self.files:
                for clazz in file.classes:
                    for method in clazz.methods:
                        if method.signature == fullname:
                            return method
        elif self.language == Language.C:
            for file in self.files:
                for method in file.methods:
                    if method.signature == fullname:
                        return method
        return None

    def get_field(self, fullname: str) -> Field | None:
        for file in self.files:
            for clazz in file.classes:
                for field in clazz.fields:
                    if field.signature == fullname:
                        return field
        return None

    def get_only_method(self) -> Method | None:
        if len(self.files) != 1:
            return None
        return self.files[0].methods[0]

    @staticmethod
    def get_triple_methods(triple_projects: tuple[Project, Project, Project], signature: str | None = None) -> None | tuple[Method, Method, Method]:
        pre_project, post_project, target_project = triple_projects
        if signature is not None:
            pre_method = pre_project.get_method(signature)
            post_method = post_project.get_method(signature)
            target_method = target_project.get_method(signature)
        else:
            pre_method = pre_project.get_only_method()
            post_method = post_project.get_only_method()
            target_method = target_project.get_only_method()
        if pre_method is None:
            logging.warning(f"❌ Pre-Patch Method 不存在: {signature}")
            return
        if post_method is None:
            logging.warning(f"❌ Post-Patch Method 不存在: {signature}")
            return
        if target_method is None:
            logging.warning(f"❌ Target Method 不存在: {signature}")
            return
        return pre_method, post_method, target_method


class File:
    def __init__(self, path: str, content: str, project: Project | None, language: Language, raw_code: str | None = None):
        self.language = language
        parser = ASTParser(content, language)
        self.parser = parser
        self.path = path
        self.name = os.path.basename(path)
        self.code = content
        self.raw_code = raw_code if raw_code is not None else content
        if project is None:
            self.project = Project("None", [CodeFile(path, content)], language)
        else:
            self.project = project

    @cached_property
    def package(self) -> str:
        assert self.language == Language.JAVA
        package_node = self.parser.query_oneshot(ast_parser.TS_JAVA_PACKAGE)
        return package_node.text.decode() if package_node is not None else "<NONE>"  # type: ignore

    @cached_property
    def imports(self) -> list[Import]:
        if self.language == Language.JAVA:
            query_result = self.parser.query(ast_parser.TS_JAVA_IMPORT)
            return [Import(import_node, self, self.language) for import_nodes in query_result.values() for import_node in import_nodes]
        elif self.language == Language.C:
            query_result = self.parser.query(ast_parser.TS_C_INCLUDE)
            return [Import(import_node, self, self.language) for import_nodes in query_result.values() for import_node in import_nodes]
        else:
            return []

    @cached_property
    def classes(self) -> list[Class]:
        if self.language == Language.JAVA:
            return [Class(class_node[0], self, self.language)
                    for class_node in self.parser.query(ast_parser.TS_JAVA_CLASS)]
        else:
            return []

    @cached_property
    def fields(self) -> list[Field]:
        return [field for clazz in self.classes for field in clazz.fields]

    @cached_property
    def methods(self) -> list[Method]:
        if self.language == Language.JAVA:
            return [method for clazz in self.classes for method in clazz.methods]
        elif self.language == Language.C:
            from func_parser import parse_functions

            # Parse from formatted code (same as what Joern receives via
            # create_code_tree) so Method.start_line matches PDG line numbers.
            funcs = parse_functions(self.code)
            methods = [
                Method(
                    node=None,
                    clazz=None,
                    file=self,
                    language=self.language,
                    name=func.name,
                    code="\n".join(self.code.split("\n")[func.start_line - 1 : func.end_line]),
                    start_line=func.start_line,
                    end_line=func.end_line,
                )
                for func in funcs
            ]

            # __releases()、__acquires() 等内核注解可能位于函数声明和左花括号之间。
            # 正则解析器会保守地跳过这类语法，因此使用 tree-sitter 补充正则遗漏的函数。
            known_names = {method.name for method in methods}
            tree_sitter_methods: list[Method] = []
            for method_node in self.parser.query_all(ast_parser.TS_C_METHOD):
                span = method_node.end_point[0] - method_node.start_point[0]
                if span > 300:
                    continue
                try:
                    method = Method(method_node, None, self, self.language)
                except AssertionError:
                    continue
                tree_sitter_methods.append(method)

            # 外层函数必须先于其内部的伪函数候选处理。例如未展开的内核宏
            # fsnotify_foreach_obj_type(type) 会被 tree-sitter 误判为名为 type 的函数。
            tree_sitter_methods.sort(key=lambda method: (method.start_line, -method.end_line))
            for method in tree_sitter_methods:
                if method.name in known_names:
                    continue
                if any(
                    confirmed.start_line <= method.start_line
                    and method.end_line <= confirmed.end_line
                    and (
                        confirmed.start_line < method.start_line
                        or method.end_line < confirmed.end_line
                    )
                    for confirmed in methods
                ):
                    continue
                methods.append(method)
                known_names.add(method.name)

            methods.sort(key=lambda method: method.start_line)
            # Tree-sitter 补充的函数虽然先追加到 methods 尾部，但随后会根据函数在源码中的起始行 start_line 重新排序，恢复源码顺序
            return methods
        else:
            return []

    def _is_nested_function(self, node: Node) -> bool:
        """Check if a function declaration is nested inside another function (e.g., function pointer parameter)"""
        # Walk up the tree to see if we're inside a function definition
        current = node
        while current is not None:
            parent = current.parent
            if parent is None:
                break
            # If parent is a compound_statement, we're inside a function body
            if parent.type == "compound_statement":
                return True
            # If parent is a parameter_list, we're a function pointer parameter
            if parent.type == "parameter_list":
                return True
            current = parent
        return False


class Import:
    def __init__(self, node: Node, file: File, language: Language):
        self.file = file
        self.node = node
        self.code = node.text.decode()  # type: ignore
        self.signature = file.path + "#" + self.code


class Class:
    def __init__(self, node: Node, file: File, language: Language):
        self.language = language
        self.file = file
        self.code = node.text.decode()  # type: ignore
        self.node = node
        name_node = node.child_by_field_name("name")
        if name_node is None:
            logging.warning(f"❌ 类名解析失败: {file.path}")
            return
        self.name = name_node.text.decode()  # type: ignore
        self.fullname = f"{file.package}.{self.name}"

    @cached_property
    def fields(self):
        file = self.file
        parser = file.parser
        class_node = self.node
        class_name = self.name
        fields: list[Field] = []
        # 防止捕获到内部类的字段
        query = f"""
        (class_declaration
            name: (identifier)@class.name
            (#eq? @class.name "{class_name}")
            body: (class_body
                (field_declaration)@field
            )
        )
        """
        for field_node in parser.query_from_node(class_node, query):
            if field_node[1] != "field":
                continue
            fields.append(Field(field_node[0], self, file))
        return fields

    @cached_property
    def methods(self):
        file = self.file
        parser = file.parser
        class_node = self.node
        class_name = self.name
        methods: list[Method] = []
        # 防止捕获到内部类的方法
        query = f"""
        (class_declaration
            name: (identifier)@class.name
            (#eq? @class.name "{class_name}")
            body: (class_body
                [(method_declaration)
                (constructor_declaration)]@method
            )
        )
        """
        for method_node in parser.query_from_node(class_node, query):
            if method_node[1] != "method":
                continue
            methods.append(Method(method_node[0], self, file, self.language))
        return methods


class Field:
    def __init__(self, node: Node, clazz: Class, file: File):
        self.name = node.child_by_field_name("declarator").child_by_field_name("name").text.decode()  # type: ignore
        self.clazz = clazz
        self.file = file
        self.code = node.text.decode()  # type: ignore
        self.signature = f"{self.clazz.fullname}.{self.name}"


class Method:
    def __init__(
        self,
        node: Node | None,
        clazz: Class | None,
        file: File,
        language: Language,
        *,
        name: str | None = None,
        code: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ):
        self.language = language
        if node is not None:
            if language == Language.JAVA:
                name_node = node.child_by_field_name("name")
                assert name_node is not None
                assert name_node.text is not None
                self.name = name_node.text.decode()
            else:
                name_node = self._extract_c_method_name_node(node)
                assert name_node is not None and name_node.type == "identifier", (
                    f"Cannot extract method name from node type={node.type}, "
                    f"text={node.text.decode()[:100]}"
                )
                assert name_node.text is not None
                self.name = name_node.text.decode()
            assert node.text is not None
            self.code = node.text.decode()
            self.start_line = node.start_point[0] + 1
            self.end_line = node.end_point[0] + 1
        elif name is not None and code is not None and start_line is not None and end_line is not None:
            # Initialized from regex parser (C code with complex macros)
            self.name = name
            self.code = code
            self.start_line = start_line
            self.end_line = end_line
        else:
            raise ValueError("Method requires either a tree-sitter node or (name, code, start_line, end_line)")
        self.clazz = clazz
        self.file = file
        self.node = node

        self.lines: dict[int, str] = {i + self.start_line: line for i, line in enumerate(self.code.split("\n"))}

        self._pdg: joern.PDG | None = None
        self.counterpart: Method | None = None
        self.method_dir: str | None = None
        self._external_diff_lines: set[int] | None = None

        self._restore_modifiers()

    def _restore_modifiers(self):
        """
        从 file.raw_code 中恢复被 del_macros() 删除的重要修饰符

        当前恢复的修饰符：
        - __init: Linux 内核函数修饰符，标记函数在内核初始化阶段执行
        - __exit: Linux 内核函数修饰符，标记函数在内核退出阶段执行
        - __user: Linux 内核指针修饰符，标记指针来自用户空间
        """
        if self.language != Language.C:
            return

        if self.file.raw_code is None:
            return

        if "__init" not in self.file.raw_code and "__exit" not in self.file.raw_code and "__user" not in self.file.raw_code:
            return

        restored_code = self._restore_init_exit_user_modifiers(
            self.code,
            self.file.raw_code,
            self.name,
            self.start_line
        )

        if restored_code != self.code:
            logging.info(f"恢复修饰符: {self.name}")
            self.code = restored_code
            self.lines = {i + self.start_line: line for i, line in enumerate(self.code.split("\n"))}

    @staticmethod
    def _restore_init_exit_user_modifiers(code: str, raw_code: str, function_name: str, start_line: int) -> str:
        """
        从 raw_code 中恢复 __init、__exit 和 __user 修饰符

        Args:
            code: 当前代码（可能丢失修饰符）
            raw_code: 原始代码（包含修饰符）
            function_name: 函数名
            start_line: 函数起始行号（1-based）

        Returns:
            恢复后的代码
        """
        signature = Method._extract_function_signature_from_raw_code(raw_code, function_name, start_line)
        if signature is None:
            return code

        if "__init" not in signature and "__exit" not in signature and "__user" not in signature:
            return code

        code_lines = code.split("\n")
        if not code_lines:
            return code

        current_signature = code_lines[0]

        if "__init" in current_signature and "__exit" in current_signature and "__user" in current_signature:
            return code

        modifiers = []
        if "__init" in signature:
            modifiers.append("__init")
        if "__exit" in signature:
            modifiers.append("__exit")
        if "__user" in signature:
            modifiers.append("__user")

        function_name_pos = current_signature.find(function_name)
        if function_name_pos == -1:
            return code

        restored_signature = current_signature[:function_name_pos] + " ".join(modifiers) + " " + current_signature[function_name_pos:]
        code_lines[0] = restored_signature

        return "\n".join(code_lines)

    @staticmethod
    def _extract_function_signature_from_raw_code(raw_code: str, function_name: str, start_line: int) -> str | None:
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

        for i in range(max(0, start_line - 6), start_line):
            line = lines[i].strip()

            if function_name in line:
                function_name_pos = line.find(function_name)
                if function_name_pos == -1:
                    continue

                signature = line[:function_name_pos + len(function_name)]

                if signature.startswith("{"):
                    for j in range(i - 1, max(0, i - 6), -1):
                        prev_line = lines[j].strip()
                        if prev_line and not prev_line.startswith("#"):
                            signature = prev_line
                            break

                return signature

        return None

    @staticmethod
    def _extract_c_method_name_node(node: Node) -> Node | None:
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            return None

        stack = [declarator]
        while stack:
            cur = stack.pop(0)
            if cur.type == "identifier":
                return cur
            stack.extend(cur.named_children)
        return None

    @classmethod
    def init_from_file_code(cls, path: str, language: Language):
        with open(path, "r") as f:
            code = f.read()
        file = File(path, code, None, language)
        parser = ASTParser(code, language)
        method_node = parser.query_oneshot(ast_parser.TS_C_METHOD)
        assert method_node is not None
        return cls(method_node, None, file, language)

    @staticmethod
    def init_method_dir(triple_methods: tuple[Method, Method, Method], cache_dir: str, fixed_method: Method | None = None) -> str:
        pre_method, post_method, target_method = triple_methods
        method_dir = f"{cache_dir}/method#{config.SLICE_LEVEL}/{pre_method.signature_r}"
        dot_dir = os.path.join(method_dir, "dot")
        diff_dir = os.path.join(method_dir, "diff")
        os.makedirs(method_dir, exist_ok=True)
        os.makedirs(dot_dir, exist_ok=True)
        os.makedirs(diff_dir, exist_ok=True)
        pre_method.method_dir, post_method.method_dir, target_method.method_dir = (method_dir,) * 3

        pre_method.write_code(method_dir)
        post_method.write_code(method_dir)
        target_method.write_code(method_dir)

        pre_method.write_dot(dot_dir)
        post_method.write_dot(dot_dir)
        target_method.write_dot(dot_dir)

        if fixed_method is not None:
            fixed_method.method_dir = method_dir
            fixed_method.write_code(method_dir)
        return method_dir

    @property
    def pdg(self) -> joern.PDG | None:
        assert self.file.project.joern is not None
        if self._pdg is None:
            self._pdg = self.file.project.joern.get_pdg(self)
        return self._pdg

    @property
    def line_pdg_pairs(self) -> dict[int, joern.PDGNode] | None:
        line_pdg_pairs = {}
        if self.pdg is None:
            return None
        for node_id in self.pdg.g.nodes():
            node = self.pdg.get_node(node_id)
            if node.line_number is None:
                continue
            line_pdg_pairs[node.line_number] = node
        return line_pdg_pairs

    @property
    def rel_line_pdg_pairs(self) -> dict[int, joern.PDGNode] | None:
        rel_line_pdg_pairs = {}
        if self.pdg is None:
            return None
        for node_id in self.pdg.g.nodes():
            node = self.pdg.get_node(node_id)
            if node.line_number is None:
                continue
            rel_line_pdg_pairs[node.line_number - self.start_line + 1] = node
        return rel_line_pdg_pairs

    @property
    def body_node(self) -> Node | None:
        if self.node is None:
            return None
        return self.node.child_by_field_name("body")

    @property
    def is_func_decl(self) -> bool:
        if self.node is None:
            return False
        return self.node.type == "declaration" and self.body_node is None

    @property
    def body_start_line(self) -> int:
        if self.body_node is not None:
            return self.body_node.start_point[0] + 1
        # Fallback: scan code to find the opening brace line
        lines = self.code.split("\n")
        for i, line in enumerate(lines):
            # Strip comments to avoid false matches on braces in comments
            stripped = line
            if "//" in stripped:
                stripped = stripped.split("//")[0]
            if "{" in stripped:
                return self.start_line + i
        # Last resort: assume body starts at function signature end
        return self.start_line

    @property
    def body_end_line(self) -> int:
        if self.body_node is None:
            return self.end_line
        else:
            return self.body_node.end_point[0] + 1

    @property
    def diff_dir(self) -> str:
        assert self.method_dir is not None
        return f"{self.method_dir}/diff"

    @property
    def dot_dir(self) -> str:
        assert self.method_dir is not None
        return f"{self.method_dir}/dot"

    @property
    def rel_line_set(self) -> set[int]:
        return set(range(self.rel_start_line, self.rel_end_line + 1))

    @property
    def parameters(self) -> list[Node]:
        if self.node is None:
            return []
        parameters_node = self.node.child_by_field_name("parameters")
        if parameters_node is None:
            return []
        parameters = ASTParser.children_by_type_name(parameters_node, "formal_parameter")
        return parameters

    @property
    def parameter_signature(self) -> str:
        parameter_signature_list = []
        for param in self.parameters:
            type_node = param.child_by_field_name("type")
            assert type_node is not None
            if type_node.type == "generic_type":
                type_identifier_node = ASTParser.child_by_type_name(type_node, "type_identifier")
                if type_identifier_node is None:
                    type_name = ""
                else:
                    assert type_identifier_node.text is not None
                    type_name = type_identifier_node.text.decode()
            else:
                assert type_node.text is not None
                type_name = type_node.text.decode()
            parameter_signature_list.append(type_name)
        return ",".join(parameter_signature_list)

    @property
    def signature(self) -> str:
        if self.language == Language.JAVA:
            assert self.clazz is not None
            return f"{self.clazz.fullname}.{self.name}({self.parameter_signature})"
        else:
            return f"{self.file.name}#{self.name}"

    @property
    def signature_r(self) -> str:
        if self.language == Language.JAVA:
            assert self.clazz is not None
            fullname_r = ".".join(self.clazz.fullname.split(".")[::-1])
            return f"{self.name}({self.parameter_signature}).{fullname_r}"
        else:
            return f"{self.name}#{self.start_line}#{self.end_line}#{self.file.name}"

    @property
    def diff_lines(self) -> set[int]:
        # 如果外部预解析了patch数据，优先使用（仅当非空时，因为坐标系统可能不匹配）
        if self._external_diff_lines is not None:
            logging.debug("[diff_lines] %s: _external_diff_lines count=%d, sorted=%s",
                          self.signature, len(self._external_diff_lines),
                          sorted(self._external_diff_lines))
            if len(self._external_diff_lines) > 0:
                logging.debug("[diff_lines] %s: using external diff lines", self.signature)
                return self._external_diff_lines
            else:
                logging.debug("[diff_lines] %s: external diff lines is EMPTY, falling through to patch_hunks",
                              self.signature)

        # 回退：通过diff方法级代码获取hunks
        patch_hunks = self.patch_hunks
        logging.debug("[diff_lines] %s: patch_hunks count=%d, start_line=%d, end_line=%d",
                      self.signature, len(patch_hunks), self.start_line, self.end_line)
        lines = set()
        for i, hunk in enumerate(patch_hunks):
            if isinstance(hunk, DelHunk):
                hunk_lines = range(hunk.a_startline, hunk.a_endline + 1)
                lines.update(hunk_lines)
            elif isinstance(hunk, ModHunk):
                hunk_lines = range(hunk.a_startline, hunk.a_endline + 1)
                lines.update(hunk_lines)
            else:
                pass

        logging.debug("[diff_lines] %s: final diff_lines count=%d, sorted=%s",
                      self.signature, len(lines), sorted(lines))
        return lines

    @property
    def rel_diff_lines(self) -> set[int]:
        if self.counterpart is None:
            logging.debug("[rel_diff_lines] %s: no counterpart, returning empty", self.signature)
            return set()

        diff_lines = self.diff_lines
        rel_lines = {line - self.start_line + 1 for line in diff_lines}
        logging.debug("[rel_diff_lines] %s: diff_lines=%s, start_line=%d → rel_diff_lines=%s",
                      self.signature, sorted(diff_lines), self.start_line, sorted(rel_lines))
        return rel_lines

    @property
    def diff_identifiers(self) -> dict[int, set[str]]:
        assert self.counterpart is not None
        diff_identifiers = {}
        for hunk in self.patch_hunks:
            if isinstance(hunk, DelHunk):
                lines = set(range(hunk.a_startline, hunk.a_endline + 1))
                criteria_identifier_a = self.identifier_by_lines(lines)
                diff_identifiers.update(criteria_identifier_a)
            elif isinstance(hunk, ModHunk):
                a_lines = set(range(hunk.a_startline, hunk.a_endline + 1))
                b_lines = set(range(hunk.b_startline, hunk.b_endline + 1))
                criteria_identifier_a = self.identifier_by_lines(a_lines)
                criteria_identifier_b = self.counterpart.identifier_by_lines(b_lines)
                lines = a_lines.union(b_lines)
                for line in lines:
                    if line in criteria_identifier_a.keys() and line in criteria_identifier_b.keys():
                        diff_identifiers[line] = criteria_identifier_a[line] - criteria_identifier_b[line]
                    elif line in criteria_identifier_a.keys():
                        diff_identifiers[line] = criteria_identifier_a[line]
        return diff_identifiers

    @cached_property
    def patch_hunks(self) -> list[Hunk]:
        print("=" * 80)
        print("🔍 PATCH_HUNKS 属性调试信息")
        print("=" * 80)

        print(f"📥 输入信息:")
        print(f"  method.name: {self.name}")
        print(f"  method.start_line: {self.start_line}")
        print(f"  method.end_line: {self.end_line}")
        print(f"  method.counterpart: {self.counterpart.name if self.counterpart else None}")
        print(f"  self.file.code 长度: {len(self.file.code)} 字符")
        print(f"  counterpart.file.code 长度: {len(self.counterpart.file.code) if self.counterpart else 0} 字符")
        print()

        assert self.counterpart is not None
        print(f"🔍 调用 get_patch_hunks 获取原始 hunks:")
        print(f"  输入文件1 (self): {self.file.path}")
        print(f"  输入文件2 (counterpart): {self.counterpart.file.path}")

        hunks = get_patch_hunks(self.file.code, self.counterpart.file.code, self.file_suffix)
        # get_patch_hunks 接收文件级代码，返回的 hunk 行号已经是文件绝对行号，
        # 直接与 self.lines、header_lines、end_line 在同一坐标系，无需偏移。

        print(f"  原始 hunks 数量: {len(hunks)}")
        for i, hunk in enumerate(hunks):
            print(f"    原始 hunk[{i}]: {type(hunk).__name__}")
            if hasattr(hunk, 'a_startline'):
                print(f"      a_startline: {hunk.a_startline}")
            if hasattr(hunk, 'a_endline'):
                print(f"      a_endline: {hunk.a_endline}")
            if hasattr(hunk, 'b_startline'):
                print(f"      b_startline: {hunk.b_startline}")
            if hasattr(hunk, 'b_endline'):
                print(f"      b_endline: {hunk.b_endline}")
            if hasattr(hunk, 'insert_line'):
                print(f"      insert_line: {hunk.insert_line}")
        print()

        print(f"🔧 过滤 hunks (只保留方法范围内的，允许部分重叠并裁剪):")
        print(f"  方法范围: [{self.start_line}, {self.end_line}]")
        original_count = len(hunks)
        for i, hunk in enumerate(hunks.copy()):
            print(f"  检查 hunk [{i}]: {type(hunk).__name__}")
            if isinstance(hunk, ModHunk):
                print(f"    a: [{hunk.a_startline}, {hunk.a_endline}], b: [{hunk.b_startline}, {hunk.b_endline}]")
                # 检查是否与方法范围有重叠
                if hunk.a_endline < self.start_line or hunk.a_startline > self.end_line:
                    hunks.remove(hunk)
                    print(f"    ❌ 移除 (完全超出方法范围)")
                else:
                    # 裁剪到方法范围内
                    if hunk.a_startline < self.start_line:
                        trim_start = self.start_line - hunk.a_startline
                        print(f"    裁剪头部: trim_start={trim_start} (hunk起始{ hunk.a_startline} < 方法起始{self.start_line})")
                        hunk.a_startline = self.start_line
                        hunk.b_startline += trim_start
                        # 裁剪代码内容
                        a_lines = hunk.a_code.split('\n')
                        b_lines = hunk.b_code.split('\n')
                        hunk.a_code = '\n'.join(a_lines[trim_start:])
                        hunk.b_code = '\n'.join(b_lines[trim_start:])
                    if hunk.a_endline > self.end_line:
                        trim_end = hunk.a_endline - self.end_line
                        print(f"    裁剪尾部: trim_end={trim_end} (hunk结束{hunk.a_endline} > 方法结束{self.end_line})")
                        hunk.a_endline = self.end_line
                        hunk.b_endline -= trim_end
                        # 裁剪代码内容
                        a_lines = hunk.a_code.split('\n')
                        b_lines = hunk.b_code.split('\n')
                        hunk.a_code = '\n'.join(a_lines[:-trim_end])
                        hunk.b_code = '\n'.join(b_lines[:-trim_end])
                    print(f"    ✅ 保留并裁剪 -> a: [{hunk.a_startline}, {hunk.a_endline}], b: [{hunk.b_startline}, {hunk.b_endline}]")
            elif isinstance(hunk, DelHunk):
                print(f"    a_startline: {hunk.a_startline}, a_endline: {hunk.a_endline}")
                if hunk.a_endline < self.start_line or hunk.a_startline > self.end_line:
                    hunks.remove(hunk)
                    print(f"    ❌ 移除 (完全超出方法范围)")
                else:
                    if hunk.a_startline < self.start_line:
                        trim_start = self.start_line - hunk.a_startline
                        print(f"    裁剪头部: trim_start={trim_start}")
                        hunk.a_startline = self.start_line
                        a_lines = hunk.a_code.split('\n')
                        hunk.a_code = '\n'.join(a_lines[trim_start:])
                    if hunk.a_endline > self.end_line:
                        trim_end = hunk.a_endline - self.end_line
                        print(f"    裁剪尾部: trim_end={trim_end}")
                        hunk.a_endline = self.end_line
                        a_lines = hunk.a_code.split('\n')
                        hunk.a_code = '\n'.join(a_lines[:-trim_end])
                    print(f"    ✅ 保留并裁剪 -> a: [{hunk.a_startline}, {hunk.a_endline}]")
            elif isinstance(hunk, AddHunk):
                print(f"    insert_line: {hunk.insert_line}")
                print(f"    b_startline: {hunk.b_startline}, b_endline: {hunk.b_endline}")
                print(f"    范围检查: {self.start_line} <= {hunk.insert_line} <= {self.end_line}")
                # AddHunk 只检查 insert_line（指向 self 版本中的位置），不检查 b_startline/b_endline
                if hunk.insert_line < self.start_line or hunk.insert_line > self.end_line:
                    hunks.remove(hunk)
                    print(f"    ❌ 移除 (超出方法范围)")
                else:
                    print(f"    ✅ 保留 (在方法范围内)")
            else:
                print(f"    ⚠️ 未知类型，保留")

        filtered_count = len(hunks)
        print(f"  过滤前: {original_count} 个 hunks")
        print(f"  过滤后: {filtered_count} 个 hunks")
        print()

        print(f"🔄 排序 hunks:")
        def sort_key(hunk: Hunk):
            if isinstance(hunk, AddHunk):
                return hunk.insert_line
            elif isinstance(hunk, ModHunk) or isinstance(hunk, DelHunk):
                return hunk.a_startline
            else:
                return 0

        hunks.sort(key=sort_key)
        print(f"  排序后的 hunks:")
        for i, hunk in enumerate(hunks):
            print(f"    hunk[{i}]: {type(hunk).__name__}")
            if isinstance(hunk, AddHunk):
                print(f"      排序键: insert_line = {hunk.insert_line}")
            elif isinstance(hunk, ModHunk) or isinstance(hunk, DelHunk):
                print(f"      排序键: a_startline = {hunk.a_startline}")
        print()

        print(f"📤 最终 patch_hunks: {len(hunks)} 个")
        print("=" * 80)
        print("✅ PATCH_HUNKS 属性获取完成")
        print("=" * 80)
        print()

        return hunks

    @property
    def header_lines(self) -> set[int]:
        return set(range(self.start_line, self.body_start_line + 1))

    @property
    def body_lines(self) -> set[int]:
        body_start_line = self.body_start_line
        body_end_line = self.body_end_line
        if self.lines[self.body_start_line].strip().endswith("{"):
            body_start_line += 1
        if self.lines[self.body_end_line].strip().endswith("}"):
            body_end_line -= 1
        return set(range(body_start_line, body_end_line + 1))

    @property
    def body_code(self) -> str:
        return "\n".join([self.lines[line] for line in sorted(self.body_lines)])

    @property
    def comment_lines(self) -> set[int]:
        if self.node is None:
            return set()
        body_node = self.node.child_by_field_name("body")
        if body_node is None:
            return set()
        comment_lines = set()
        query = """
        (line_comment)@line_comment
        (block_comment)@block_comment
        """
        comment_nodes = self.file.parser.query_from_node(body_node, query)
        line_comments = [comment[0] for comment in comment_nodes if comment[1] == "line_comment"]
        block_comments = [comment[0] for comment in comment_nodes if comment[1] == "block_comment"]
        for comment_node in line_comments:
            line = comment_node.start_point[0] + 1
            if self.lines[line].strip() == comment_node.text.decode().strip():  # type: ignore
                comment_lines.add(line)
        for comment_node in block_comments:
            start_line = comment_node.start_point[0] + 1
            end_line = comment_node.end_point[0] + 1
            if self.lines[start_line].strip().startswith("/*"):
                comment_lines.update(range(start_line, end_line + 1))
        return comment_lines

    def code_by_lines(self, lines: set[int], *, placeholder: str | None = None,
                      keep_lines: set[int] | None = None,
                      pre_diff_lines: set[int] | None = None) -> str:
        """
        Extract code by line numbers.

        Args:
            lines: Line numbers to include.
            placeholder: If set, insert placeholder for gaps between lines.
            keep_lines: Lines that should NEVER be replaced with placeholder.
                       Used to preserve diff lines in their entirety.
            pre_diff_lines: Pre method's diff lines. If any line in the gap is in pre_diff_lines,
                          output actual code instead of placeholder.
        """
        if placeholder is None:
            result = "\n".join([self.rel_lines[line] for line in sorted(lines)])
            return result + "\n"
        else:
            logging.info("CODE_BY_LINES[%s]: with placeholder, lines=%d, keep_lines=%s, pre_diff_lines=%s",
                         self.name, len(lines),
                         sorted(keep_lines) if keep_lines else None,
                         sorted(pre_diff_lines) if pre_diff_lines else None)
            code_with_placeholder = ""
            last_line = 0
            placeholder_counter = 0
            placeholder_line_nums: set[int] = set()
            for line in sorted(lines):
                if line - last_line > 1:
                    is_comment = True
                    for i in range(last_line + 1, line):
                        if self.rel_lines.get(i, "").strip() == "":
                            continue
                        if not self.rel_lines.get(i, "").strip().startswith("//"):
                            is_comment = False
                            break
                    if is_comment:
                        pass
                    elif line - last_line == 2 and (self.rel_lines.get(line - 1, "").strip() == "" or self.rel_lines.get(line - 1, "").strip().startswith("//")):
                        pass
                    else:
                        # Check if any line in the gap is a "keep_lines" line
                        # or a "pre_diff_lines" line
                        # If so, we need to output the actual code for those lines
                        gap_has_special_lines = False
                        if keep_lines is not None or pre_diff_lines is not None:
                            for i in range(last_line + 1, line):
                                if keep_lines is not None and i in keep_lines:
                                    gap_has_special_lines = True
                                    break
                                if pre_diff_lines is not None and i in pre_diff_lines:
                                    gap_has_special_lines = True
                                    break
                        if not gap_has_special_lines:
                            code_with_placeholder += f"{placeholder}\n"
                            placeholder_counter += 1
                            placeholder_line_nums.update(range(last_line + 1, line))
                        else:
                            # Output actual code for keep_lines/pre_diff_lines, PLACEHOLDER for others.
                            # Group consecutive non-special lines into ONE placeholder per run
                            # so that placeholder count matches hunk count in recover_placeholder.
                            i = last_line + 1
                            while i < line:
                                if keep_lines is not None and i in keep_lines:
                                    code_with_placeholder += self.rel_lines[i] + "\n"
                                    i += 1
                                elif pre_diff_lines is not None and i in pre_diff_lines:
                                    code_with_placeholder += self.rel_lines[i] + "\n"
                                    i += 1
                                else:
                                    # Start of a run of non-special lines → output ONE placeholder
                                    code_with_placeholder += f"{placeholder}\n"
                                    placeholder_counter += 1
                                    while i < line and \
                                          not (keep_lines is not None and i in keep_lines) and \
                                          not (pre_diff_lines is not None and i in pre_diff_lines):
                                        placeholder_line_nums.add(i)
                                        i += 1
                code_with_placeholder += self.rel_lines.get(line, "") + "\n"
                last_line = line
            # Store the set of original line numbers that became placeholders,
            # so recover_placeholder/reduced_hunks can use the exact same mapping.
            self._placeholder_line_nums = placeholder_line_nums
            logging.info("CODE_BY_LINES[%s]: stored _placeholder_line_nums count=%d (sorted=%s)",
                         self.name, len(placeholder_line_nums), sorted(placeholder_line_nums))
            return code_with_placeholder

    def reduced_hunks(self, slines: set[int]) -> list[str]:
        print("=" * 80)
        print("🔍 REDUCED_HUNKS 函数调试信息")
        print("=" * 80)

        print(f"📥 输入参数:")
        print(f"  method.name: {self.name}")
        print(f"  slines (切片行): {sorted(slines)}")
        print(f"  self.rel_line_set: {sorted(self.rel_line_set)}")
        print()

        print(f"🔍 计算占位符行:")
        if hasattr(self, '_placeholder_line_nums') and self._placeholder_line_nums is not None:
            placeholder_lines = self._placeholder_line_nums
            logging.info("REDUCED_HUNKS[%s]: using stored _placeholder_line_nums, count=%d",
                         self.name, len(placeholder_lines))
        else:
            placeholder_lines = self.rel_line_set - slines
            logging.info("REDUCED_HUNKS[%s]: _placeholder_line_nums not set, fallback to rel_line_set - slines, count=%d",
                         self.name, len(placeholder_lines))
        logging.info("REDUCED_HUNKS[%s]: placeholder_lines (sorted)=%s", self.name, sorted(placeholder_lines))
        print(f"  placeholder_lines: {sorted(placeholder_lines)}")
        print()

        print(f"🔍 调用 self.code_hunks(placeholder_lines):")
        print(f"  输入 placeholder_lines: {sorted(placeholder_lines)}")
        result = self.code_hunks(placeholder_lines)
        print(f"  输出 hunks 数量: {len(result)}")
        for i, hunk in enumerate(result):
            print(f"    hunk[{i}]: {repr(hunk[:100])}{'...' if len(hunk) > 100 else ''}")
        print()

        print("=" * 80)
        print("✅ REDUCED_HUNKS 函数执行完成")
        print("=" * 80)
        print()

        return result

    def code_hunks(self, lines: set[int]) -> list[str]:
        print("=" * 80)
        print("🔍 CODE_HUNKS 函数调试信息")
        print("=" * 80)

        print(f"📥 输入参数:")
        print(f"  method.name: {self.name}")
        print(f"  lines: {sorted(lines)}")
        print()

        print(f"🔍 调用 utils.group_consecutive_ints:")
        lines_list = list(lines)
        print(f"  输入 lines_list: {lines_list}")
        lineg = utils.group_consecutive_ints(lines_list)
        print(f"  输出 lineg: {lineg}")
        print()

        print(f"🔧 处理每个连续行组:")
        hunks: list[str] = []
        for i, g in enumerate(lineg):
            print(f"  处理组{i+1}: {g}")
            hunk = self.code_by_lines(set(g))
            hunks.append(hunk)
            print(f"    生成的 hunk: {repr(hunk[:100])}{'...' if len(hunk) > 100 else ''}")
        print()

        print(f"📤 最终结果:")
        print(f"  hunks 数量: {len(hunks)}")
        for i, hunk in enumerate(hunks):
            print(f"    hunk[{i}]: {repr(hunk[:100])}{'...' if len(hunk) > 100 else ''}")
        print()

        print("=" * 80)
        print("✅ CODE_HUNKS 函数执行完成")
        print("=" * 80)
        print()

        return hunks

    def recover_placeholder(self, code: str, slice_lines: set[int], placeholder: str) -> str | None:
        print("=" * 80)
        print("🔍 RECOVER_PLACEHOLDER 函数调试信息")
        print("=" * 80)

        print(f"📥 输入参数:")
        print(f"  method.name: {self.name}")
        print(f"  code 长度: {len(code)} 字符")
        print(f"  slice_lines: {sorted(slice_lines)}")
        print(f"  placeholder: {repr(placeholder)}")
        print()

        print(f"🔍 调用 self.reduced_hunks(slice_lines):")
        print(f"  输入 slice_lines: {sorted(slice_lines)}")
        placeholder_hunks = self.reduced_hunks(slice_lines)
        logging.info("RECOVER_PLACEHOLDER[%s]: reduced_hunks returned %d hunks", self.name, len(placeholder_hunks))
        for i, hunk in enumerate(placeholder_hunks):
            logging.info("RECOVER_PLACEHOLDER[%s]: hunk[%d] content=%r", self.name, i, hunk[:300])
        print(f"  输出 placeholder_hunks 数量: {len(placeholder_hunks)}")
        for i, hunk in enumerate(placeholder_hunks):
            print(f"    hunk[{i}]: {repr(hunk[:100])}{'...' if len(hunk) > 100 else ''}")
        print()

        print(f"🔍 分析输入代码中的占位符:")
        code_lines = code.split("\n")
        print(f"  code 行数: {len(code_lines)}")
        print(f"  code 内容预览:")
        for i, line in enumerate(code_lines[:10]):  # 显示前10行
            print(f"    {i+1}: {repr(line)}")
        if len(code_lines) > 10:
            print(f"    ... (还有 {len(code_lines)-10} 行)")
        print()

        print(f"🔍 统计占位符数量:")
        placeholder_text = placeholder.strip()
        placeholder_count = sum(1 for line in code_lines if line.strip() == placeholder_text)
        hunks_count = len(placeholder_hunks)
        logging.info("RECOVER_PLACEHOLDER[%s]: code has %d placeholders, hunks has %d items", self.name, placeholder_count, hunks_count)
        if placeholder_count != hunks_count:
            logging.warning("RECOVER_PLACEHOLDER[%s]: MISMATCH! placeholder=%d hunk=%d -> offset will be wrong", self.name, placeholder_count, hunks_count)
        print(f"  code 中占位符数量: {placeholder_count}")
        print(f"  placeholder_hunks 数量: {hunks_count}")
        print(f"  占位符内容: {repr(placeholder)}")
        print()

        print(f"🔍 查找代码中的占位符行:")
        placeholder_lines = []
        for i, line in enumerate(code_lines):
            if line.strip() == placeholder_text:
                placeholder_lines.append((i+1, line))
                print(f"    第{i+1}行: {repr(line)}")
        print(f"  找到占位符行数: {len(placeholder_lines)}")
        print()

        # 检查占位符数量是否一致
        print(f"🔍 检查占位符数量一致性:")
        if placeholder_count != hunks_count:
            print(f"  ⚠️ 数量不匹配: {placeholder_count} != {hunks_count}")
            if placeholder_count > hunks_count:
                print(f"  ⚠️ 占位符过多(LLM添加了额外的placeholder)，将替换前{hunks_count}个，移除多余的{placeholder_count - hunks_count}个")
            else:
                print(f"  ⚠️ 占位符过少，将替换所有{placeholder_count}个，剩余{hunks_count - placeholder_count}个hunk无法恢复")
        else:
            print(f"  ✅ 数量匹配: {placeholder_count} == {hunks_count}")
        print()

        print(f"🔧 开始替换占位符:")
        result = ""
        hunks_copy = placeholder_hunks.copy()  # 保存原始列表用于调试
        print(f"  初始 hunks_copy: {len(hunks_copy)} 个")
        print()

        for i, line in enumerate(code_lines):
            print(f"  处理第{i+1}行: {repr(line)}")
            if line.strip().lower() == placeholder.strip().lower():
                if hunks_copy:
                    replacement = hunks_copy.pop(0)
                    logging.info("RECOVER_PLACEHOLDER[%s]: line %d PLACEHOLDER -> hunk[%d/%d] = %r",
                                 self.name, i+1, len(hunks_copy), len(placeholder_hunks), replacement[:200])
                    result += replacement
                    print(f"    ✅ 替换为: {repr(replacement[:100])}{'...' if len(replacement) > 100 else ''}")
                    print(f"    剩余 hunks: {len(hunks_copy)} 个")
                else:
                    # 多余占位符：直接移除（LLM误加的placeholder）
                    print(f"    ⚠️ 多余占位符，已移除")
            else:
                result += line + "\n"
                print(f"    ➡️ 保持原样")
        print()

        print(f"📤 最终结果:")
        print(f"  result 长度: {len(result)} 字符")
        print(f"  result 内容预览:")
        result_lines = result.split("\n")
        for i, line in enumerate(result_lines[:10]):  # 显示前10行
            print(f"    {i+1}: {repr(line)}")
        if len(result_lines) > 10:
            print(f"    ... (还有 {len(result_lines)-10} 行)")
        print()

        print("=" * 80)
        print("✅ RECOVER_PLACEHOLDER 函数执行完成")
        print("=" * 80)
        print()

        return result

    def code_by_exclude_lines(self, lines: set[int], *, placeholder: str | None) -> str:
        exclude_lines = self.rel_line_set - lines
        return self.code_by_lines(exclude_lines, placeholder=placeholder)

    def identifier_by_lines(self, lines: set[int]) -> dict[int, set[str]]:
        identifiers: dict[int, set[str]] = {}
        if self.language == Language.C:
            identifier_nodes = self.file.parser.get_all_identifier_node()
            for node in identifier_nodes:
                if node.parent is not None and node.parent.type == "unary_expression":
                    line = node.parent.start_point[0] + 1
                    if line in lines:
                        assert node.parent.text is not None
                        node_text = node.parent.text.decode()
                        try:
                            identifiers[line].add(node_text)
                        except KeyError:
                            identifiers[line] = {node_text}
                else:
                    line = node.start_point[0] + 1
                    if line in lines:
                        assert node.text is not None
                        node_text = node.text.decode()
                        try:
                            identifiers[line].add(node_text)
                        except KeyError:
                            identifiers[line] = {node_text}
        return identifiers

    @property
    def normalized_body_code(self) -> str:
        return format.normalize(self.body_code)

    @property
    def formatted_code(self) -> str:
        return format.format(
            self.code,
            self.language,
            del_comment=False,
            del_linebreak=False,
            add_bracket=False,
            del_macro=False,
        )

    @property
    def rel_start_line(self) -> int:
        return 1

    @property
    def rel_end_line(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def rel_body_start_line(self) -> int:
        return self.body_start_line - self.start_line + 1

    @property
    def rel_body_end_line(self) -> int:
        return self.body_end_line - self.start_line + 1

    @property
    def rel_lines(self) -> dict[int, str]:
        return {line - self.start_line + 1: code for line, code in self.lines.items()}

    @property
    def length(self):
        return self.end_line - self.start_line + 1

    @property
    def file_suffix(self):
        if self.language == Language.C:
            suffix = ".c"
        elif self.language == Language.JAVA:
            suffix = ".java"
        else:
            suffix = ""
        return suffix

    def write_dot(self, dir: str | None = None):
        assert self.pdg is not None
        dot_name = f"{self.file.project.project_name}.dot"
        if dir is not None:
            dot_path = os.path.join(dir, dot_name)
        else:
            dot_path = os.path.join(self.dot_dir, dot_name)
        nx.nx_agraph.write_dot(self.pdg.g, dot_path)

    def write_code(self, dir: str | None = None):
        assert self.method_dir is not None
        file_name = f"{self.file.project.project_name}{self.file_suffix}"
        if dir is not None:
            code_path = os.path.join(dir, file_name)
        else:
            code_path = os.path.join(self.method_dir, file_name)
        with open(code_path, "w") as f:
            f.write(self.code)

    def code_by_lines_ppathf(self, lines: set[int], *, placeholder: bool = False) -> str:
        if not placeholder:
            result = "\n".join([self.rel_lines[line] for line in sorted(lines)])
            return result + "\n"
        else:
            code_with_placeholder = ""
            last_line = 0
            placeholder_counter = 0
            for line in sorted(lines):
                if line - last_line > 1:
                    is_comment = True
                    for i in range(last_line + 1, line):
                        if self.rel_lines[i].strip() == "":
                            continue
                        if not self.rel_lines[i].strip().startswith("//"):
                            is_comment = False
                            break
                    if is_comment:
                        pass
                    elif line - last_line == 2 and (self.rel_lines[line - 1].strip() == "" or self.rel_lines[line - 1].strip().startswith("//")):
                        pass
                    else:
                        code_with_placeholder += f"/* Placeholder_{placeholder_counter} */\n"
                        placeholder_counter += 1
                code_with_placeholder += self.rel_lines[line] + "\n"
                last_line = line
            return code_with_placeholder

    @staticmethod
    def backward_slice(criteria_lines: set[int], criteria_nodes: list[PDGNode], criteria_identifier: dict[int, set[str]], all_nodes: dict[int, list[PDGNode]], level: int) -> tuple[set[int], list[PDGNode]]:
        result_lines = criteria_lines.copy()
        result_nodes = criteria_nodes.copy()
        if level == 0:
            level = sys.maxsize

        # CFG 切片
        for slice_line in criteria_lines:
            for node in all_nodes[slice_line]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                for pred_node in node.pred_cfg_nodes:
                    if pred_node.line_number is None or int(pred_node.line_number) == sys.maxsize:
                        continue
                    result_lines.add(int(pred_node.line_number))
                    result_nodes.append(pred_node)

        # DDG 切片
        for sline in criteria_lines:
            for node in all_nodes[sline]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                visited = set()
                queue: deque[tuple[PDGNode, int]] = deque([(node, 0)])
                while queue:
                    node, depth = queue.popleft()
                    if node not in visited:
                        visited.add(node)
                        if node not in result_nodes:
                            result_nodes.append(node)
                        if node.line_number is not None:
                            result_lines.add(node.line_number)
                        if depth < level:
                            for pred_node, edge in node.pred_ddg:
                                if pred_node.line_number is None or int(pred_node.line_number) == sys.maxsize or node.line_number is None:
                                    continue
                                if pred_node.line_number > node.line_number:
                                    continue
                                if edge not in node.code:
                                    continue
                                if len(criteria_identifier) > 0:
                                    if node.line_number in criteria_identifier:
                                        if edge not in criteria_identifier[node.line_number]:
                                            continue
                                queue.append((pred_node, depth + 1))

        return result_lines, result_nodes

    @staticmethod
    def forward_slice(criteria_lines: set[int], criteria_nodes: list[PDGNode], criteria_identifier: dict[int, set[str]], all_nodes: dict[int, list[PDGNode]], level: int) -> tuple[set[int], list[PDGNode]]:
        result_lines = criteria_lines.copy()
        result_nodes = criteria_nodes.copy()
        if level == 0:
            level = sys.maxsize

        # CFG 切片
        for slice_line in criteria_lines:
            for node in all_nodes[slice_line]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                if node.line_number is None:
                    continue
                for succ_node in node.succ_cfg_nodes:
                    if succ_node.line_number is None or int(succ_node.line_number) == sys.maxsize:
                        continue
                    if succ_node.line_number < node.line_number:
                        continue  # 防止循环依赖
                    result_lines.add(int(succ_node.line_number))
                    result_nodes.append(succ_node)

        # DDG 切片
        for sline in criteria_lines:
            for node in all_nodes[sline]:
                if node.type == "METHOD" or "METHOD_RETURN" in ast.literal_eval(node.type):
                    continue
                visited = set()
                queue: deque[tuple[PDGNode, int]] = deque([(node, 0)])
                while queue:
                    node, depth = queue.popleft()
                    if node not in visited:
                        visited.add(node)
                        if node not in result_nodes:
                            result_nodes.append(node)
                        if node.line_number is not None:
                            result_lines.add(node.line_number)
                        if depth < level:
                            for succ_node, edge in node.succ_ddg:
                                if edge not in node.code:
                                    continue
                                if succ_node.line_number is None or int(succ_node.line_number) == sys.maxsize or node.line_number is None:
                                    continue
                                if succ_node.line_number < node.line_number:
                                    continue
                                if node.line_number in criteria_identifier:
                                    if edge not in criteria_identifier[node.line_number]:
                                        continue
                                queue.append((succ_node, depth + 1))

        return result_lines, result_nodes

    def slice(self, criteria_lines: set[int], criteria_identifier: dict[int, set[str]], backward_slice_level: int = 4, forward_slice_level: int = 4, is_rel: bool = False):
        assert self.pdg is not None
        if is_rel:
            criteria_lines = set([line + self.start_line - 1 for line in criteria_lines])

        all_lines = set(self.lines.keys())
        all_nodes: dict[int, list[PDGNode]] = {
            line: self.pdg.get_nodes_by_line_number(line) for line in all_lines
        }
        criteria_nodes: list[PDGNode] = []
        for line in criteria_lines:
            for node in self.pdg.get_nodes_by_line_number(line):
                node.is_patch_node = True
                node.add_attr("color", "red")
                criteria_nodes.append(node)

        slice_result_lines = set(criteria_lines)
        slice_result_lines |= self.header_lines
        slice_result_lines.add(self.end_line)

        logging.debug(
            "[slice] %s: start_line=%d, body_start_line=%d, end_line=%d, header_lines=%s, "
            "node_type=%s, body_node=%s",
            self.signature, self.start_line, self.body_start_line, self.end_line,
            sorted(self.header_lines),
            self.node.type if self.node else "None",
            "present" if self.body_node else "None",
        )
        logging.debug(
            "[slice] %s: after header_lines+end_line, abs_lines count=%d (sorted first 20: %s)",
            self.signature, len(slice_result_lines), sorted(slice_result_lines)[:20],
        )

        # PDG 切片
        result_lines, backward_nodes = self.backward_slice(
            criteria_lines, criteria_nodes, criteria_identifier, all_nodes, backward_slice_level)
        slice_result_lines.update(result_lines)
        result_lines, forward_nodes = self.forward_slice(
            criteria_lines, criteria_nodes, criteria_identifier, all_nodes, forward_slice_level)
        slice_result_lines.update(result_lines)
        slice_nodes = criteria_nodes + backward_nodes + forward_nodes
        slice_result_rel_lines = set(
            [line - self.start_line + 1 for line in slice_result_lines if line >= self.start_line])

        logging.debug(
            "[slice] %s: after PDG, rel_lines count=%d (sorted first 20: %s)",
            self.signature, len(slice_result_rel_lines), sorted(slice_result_rel_lines)[:20],
        )

        # AST 切片
        if self.language == Language.JAVA:
            ast = ASTParser(self.code, self.language)
            body_node = ast.query_oneshot("(method_declaration body: (block)@body)")
            if body_node is None:
                logging.warning(f"❌ Method Body AST 不存在, Method: {self.signature}")
                return
            slice_result_rel_lines = self.ast_dive_java(body_node, slice_result_rel_lines)
            slice_result_lines = set([line + self.start_line - 1 for line in slice_result_rel_lines])
        elif self.language == Language.C:
            ast = ASTParser(self.code, self.language)
            body_node = ast.query_oneshot("(function_definition body: (compound_statement)@body)")
            if body_node is None:
                logging.warning(f"❌ Method Body AST 不存在, Method: {self.signature}")
                return
            rel_lines_before_ast = set(slice_result_rel_lines)
            logging.debug(
                "[slice] %s: body_node lines %d-%d, rel_lines before AST dive count=%d",
                self.signature,
                body_node.start_point[0] + 1, body_node.end_point[0] + 1,
                len(slice_result_rel_lines),
            )
            slice_result_rel_lines = self.ast_dive_c(body_node, slice_result_rel_lines)
            added_by_ast = slice_result_rel_lines - rel_lines_before_ast
            removed_by_ast = rel_lines_before_ast - slice_result_rel_lines
            if removed_by_ast:
                logging.warning(
                    "[slice] %s: AST dive REMOVED %d lines: %s",
                    self.signature, len(removed_by_ast), sorted(removed_by_ast)[:20],
                )
            if added_by_ast:
                logging.debug(
                    "[slice] %s: AST dive added %d lines (first 20: %s)",
                    self.signature, len(added_by_ast), sorted(added_by_ast)[:20],
                )
            slice_result_lines = set([line + self.start_line - 1 for line in slice_result_rel_lines])
        sliced_code = self.code_by_lines(slice_result_rel_lines)
        return slice_result_lines, slice_result_rel_lines, slice_nodes, sliced_code

    def slice_by_diff_lines(self, backward_slice_level: int = 4, forward_slice_level: int = 4, need_criteria_identifier: bool = False, write_dot: bool = False):
        criteria_identifier = self.diff_identifiers if need_criteria_identifier else {}
        slice_results = self.slice(self.diff_lines, criteria_identifier,
                                   backward_slice_level, forward_slice_level, is_rel=False)
        if write_dot and slice_results is not None:
            assert self.pdg is not None and self.method_dir is not None
            slice_nodes = slice_results[2]
            g = nx.subgraph(self.pdg.g, [node.node_id for node in slice_nodes])
            os.makedirs(self.method_dir, exist_ok=True)
            role = self.file.project.project_name
            nx.nx_agraph.write_dot(g, os.path.join(
                self.dot_dir, f"{role}#{backward_slice_level}#{forward_slice_level}.dot"))
        return slice_results

    @staticmethod
    def ast_dive_java(root: Node, slice_lines: set[int]) -> set[int]:
        def is_in_node(line: int, node: Node) -> bool:
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            return node_start_line <= line <= node_end_line
        for node in root.named_children:
            tmp_lines = set()
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            for sline in slice_lines:
                if is_in_node(sline, node):
                    tmp_lines.add(sline)
            if len(tmp_lines) == 0:
                continue
            if node.type == "expression_statement":
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
            elif node.type == "if_statement":
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                slice_lines.update([node_start_line])
                slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                consequence_node = node.child_by_field_name("consequence")
                if consequence_node is None:
                    continue
                slice_lines.update([consequence_node.start_point[0] + 1, consequence_node.end_point[0] + 1])
                Method.ast_dive_java(consequence_node, slice_lines)

                alternative_node = node.child_by_field_name("alternative")
                if alternative_node is None:
                    continue
                next_alternative_node = alternative_node.child_by_field_name("alternative")
                if next_alternative_node is None:
                    slice_lines.update([alternative_node.start_point[0] + 1], [alternative_node.end_point[0] + 1])
                else:
                    slice_lines.update([alternative_node.start_point[0] + 1])
                Method.ast_dive_java(alternative_node, slice_lines)
            elif node.type == "try_statement":
                slice_lines.update([node_start_line, node_end_line])
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                Method.ast_dive_java(body_node, slice_lines)

                catch_node = ASTParser.children_by_type_name(node, "catch_clause")
                for node in catch_node:
                    slice_lines.update([node.start_point[0] + 1, node.end_point[0] + 1])
                    body_node = node.child_by_field_name("body")
                    if body_node is None:
                        continue
                    Method.ast_dive_java(body_node, slice_lines)

                finally_node = ASTParser.child_by_type_name(node, "finally_clause")
                if finally_node is None:
                    continue
                slice_lines.update([finally_node.start_point[0] + 1, finally_node.end_point[0] + 1])
                Method.ast_dive_java(finally_node, slice_lines)
            elif node.type == "for_statement":
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                init_node = node.child_by_field_name("init")
                if init_node is None:
                    continue
                if init_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([init_node.start_point[0] + 1, init_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                if condition_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                update_node = node.child_by_field_name("update")
                if update_node is None:
                    continue
                if update_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([update_node.start_point[0] + 1, update_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                Method.ast_dive_java(body_node, slice_lines)
            elif node.type == "block":
                slice_lines.update([node_start_line, node_end_line])
                Method.ast_dive_java(node, slice_lines)
            else:
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
        return slice_lines

    def ast_dive_c(self, root: Node, slice_lines: set[int]) -> set[int]:
        def is_in_node(line: int, node: Node) -> bool:
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            return node_start_line <= line <= node_end_line
        for node in root.named_children:
            tmp_lines = set()
            node_start_line = node.start_point[0] + 1
            node_end_line = node.end_point[0] + 1
            for sline in slice_lines:
                if is_in_node(sline, node):
                    tmp_lines.add(sline)
            if len(tmp_lines) == 0:
                continue
            if node.type == "expression_statement":
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
            elif node.type == "if_statement":
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                slice_lines.update([node_start_line])
                slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                consequence_node = node.child_by_field_name("consequence")
                if consequence_node is None:
                    continue
                slice_lines.update([consequence_node.start_point[0] + 1, consequence_node.end_point[0] + 1])
                self.ast_dive_c(consequence_node, slice_lines)

                alternative_node = node.child_by_field_name("alternative")
                if alternative_node is None:
                    continue
                next_alternative_node = alternative_node.child_by_field_name("alternative")
                if next_alternative_node is None:
                    slice_lines.update([alternative_node.start_point[0] + 1], [alternative_node.end_point[0] + 1])
                else:
                    slice_lines.update([alternative_node.start_point[0] + 1])
                self.ast_dive_c(alternative_node, slice_lines)
            elif node.type == "for_statement":
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                init_node = node.child_by_field_name("initializer")
                if init_node is None:
                    continue
                if init_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([init_node.start_point[0] + 1, init_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                if condition_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                update_node = node.child_by_field_name("update")
                if update_node is None:
                    continue
                if update_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([update_node.start_point[0] + 1, update_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                self.ast_dive_c(body_node, slice_lines)
            elif node.type == "switch_statement":
                body_node = node.child_by_field_name("body")
                if body_node is None:
                    continue
                condition_node = node.child_by_field_name("condition")
                if condition_node is None:
                    continue
                if condition_node.start_point[0] + 1 in slice_lines:
                    slice_lines.update([condition_node.start_point[0] + 1, condition_node.end_point[0] + 1])
                    slice_lines.update([body_node.start_point[0] + 1, body_node.end_point[0] + 1])
                self.ast_dive_c(body_node, slice_lines)
            elif node.type == "block" or node.type == "compound_statement":
                slice_lines.update([node_start_line, node_end_line])
                self.ast_dive_c(node, slice_lines)
            else:
                slice_lines.update([line for line in range(node_start_line, node_end_line + 1)])
        return slice_lines
