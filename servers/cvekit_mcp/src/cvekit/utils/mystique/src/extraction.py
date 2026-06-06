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


import hashlib
import os
import re
import subprocess

import format
from config import CTAGS_PATH
from difftools import git_diff_code, parse_diff
from git import Repo
from pydriller import GitRepository
from pydriller.domain.commit import ModificationType
from pydriller.utils.conf import Conf


def get_file_content_at_commit(repo_path, commit_hash, file_path):
    repo = Repo(repo_path)
    commit = repo.commit(commit_hash)
    try:
        file_content = commit.tree / file_path
        print(f"Git对象引用: {file_content}")
        print(f"对象类型: {type(file_content)}")
        print(f"对象哈希: {file_content.hexsha}")
        print(f"对象大小: {file_content.size} bytes")
        
        # 获取实际的文件内容
        actual_content = file_content.data_stream.read().decode("utf-8")
        print(f"文件内容长度: {len(actual_content)} 字符")
        print(f"文件内容前100字符: {actual_content[:100]}...")
        
        return actual_content
    except KeyError:
        print(f"文件 {file_path} 在提交 {commit_hash} 中不存在")
        return None


def get_method_code(modified_file_code: str, filename: str, method_name: str):
    fp = open(filename, "w")
    fp.write(modified_file_code)
    fp.close()

    if "::" in method_name.replace(" ", ""):
        method_name = method_name.replace(" ", "").split("::")[1]
    if method_name.startswith("*"):
        method_name = method_name[1:]
    number = re.compile(r"(\d+)")

    finding_cfiles = subprocess.check_output(
        CTAGS_PATH + ' -f - --kinds-C=* --fields=neKSt "' + filename + '"',
        stderr=subprocess.STDOUT,
        shell=True,
    ).decode(errors="ignore")
    alllist = str(finding_cfiles)

    method_code = ""

    for result in alllist.split("\n"):
        if result == "" or result == " " or result == "\n":
            continue

        if len(result.split("\t")) < 7:
            continue

        funcname = result.split("\t")[0]

        if (
            result.split("\t")[3] == "f"
            and "function:" not in result.split("\t")[5]
            and "function:" not in result.split("\t")[6]
            and "end:" in result.split("\t")[-1]
        ):
            startline = int(result.split("\t")[4].replace("line:", ""))
            endline = int(result.split("\t")[-1].replace("end:", ""))
            if funcname.replace(" ", "").replace("*", "") == method_name.replace(
                " ", ""
            ).replace("*", ""):
                method_code = "\n".join(
                    modified_file_code.split("\n")[startline - 1 : endline]
                )
                break
        elif "function" in result.split("\t"):
            elemList = result.split("\t")
            j = elemList.index("function")
            startline = -1
            endline = -1
            while j < len(elemList):
                elem = elemList[j]
                if "line:" in elem and number.search(elem) is not None:
                    startline = int(number.search(elem).group(0))  # type: ignore
                elif "end:" in elem and number.search(elem) is not None:
                    endline = int(number.search(elem).group(0))  # type: ignore
                if startline >= 0 and endline >= 0:
                    break
                j += 1
            if funcname.replace(" ", "") == method_name.replace(" ", ""):
                method_code = "\n".join(
                    modified_file_code.split("\n")[startline - 1 : endline]
                )
                break

    os.remove(filename)
    return method_code


def extract_commit_contents(repo_path: str, commit_id: str):
    conf = Conf(
        {
            "path_to_repo": str(repo_path),
            "skip_whitespaces": True,
            "include_remotes": True,
        }
    )
    repo = GitRepository(repo_path, conf=conf)
    method_info = []
    for file in repo.get_commit(commit_id).modifications:
        try:
            if file.change_type != ModificationType.MODIFY:
                continue
            if file.filename.split(".")[-1] not in [
                "c",
                "h",
                "cpp",
                "cxx",
                "c++",
                "cc",
                "hpp",
                "hxx",
                "C",
            ]:
                continue
            if "test/" in file.filename and "tests/" in file.filename:
                continue

            filename = file.old_path
            print("filename=======", filename)
            assert filename is not None
            pre_file_code = format.format_and_del_comment_c_cpp(file.source_code_before)
            # print("pre_file_code=======", pre_file_code)
            post_file_code = format.format_and_del_comment_c_cpp(file.source_code)
            # print("post_file_code=======", post_file_code)
            diff = git_diff_code(pre_file_code, post_file_code)
            # print("diff=======", diff)
            patch_info = parse_diff(diff, filename)
            # print("patch_info=======", patch_info)
            methods_delete_add, pre_file_methods = get_modified_map(
                pre_file_code, patch_info["delete"], filename.replace("/", "_")
            )
            if methods_delete_add == {} and pre_file_methods == []:
                return []
            methods_add_delete, post_file_methods = get_modified_map(
                post_file_code, patch_info["add"], filename.replace("/", "_")
            )
            if methods_add_delete == {} and post_file_methods == []:
                return []
            new_old_map, old_new_map = get_old_new_map(patch_info)
            for line_info in methods_delete_add.keys():
                st = int(line_info.split("##")[0])
                ed = int(line_info.split("##")[1])
                not_change_line = -1
                for line in range(st, ed + 1):
                    if line in old_new_map.keys():
                        not_change_line = line
                        break
                # 方法是完全删除
                if not_change_line == -1:
                    del methods_delete_add[line_info]
                    continue
                for add_st_ed in methods_add_delete.keys():
                    st_add = int(add_st_ed.split("##")[0])
                    ed_add = int(add_st_ed.split("##")[1])
                    if (
                        old_new_map[not_change_line] >= st_add
                        and old_new_map[not_change_line] <= ed_add
                    ):
                        methods_delete_add[line_info] = add_st_ed
                        methods_add_delete[add_st_ed] = line_info
                        break

                # 该方法只有删除行，没有新增行
                if methods_delete_add[line_info] == "":
                    for result in post_file_methods:
                        if result == "" or result == " " or result == "\n":
                            continue

                        funcname = result.split("\t")[0]
                        if len(result.split("\t")) < 7:
                            continue

                        if (
                            result.split("\t")[3] == "f"
                            and "function:" not in result.split("\t")[5]
                            and "function:" not in result.split("\t")[6]
                            and "end:" in result.split("\t")[-1]
                        ):
                            startline = int(result.split("\t")[4].replace("line:", ""))
                            endline = int(result.split("\t")[-1].replace("end:", ""))
                            if (
                                old_new_map[not_change_line] >= startline
                                and old_new_map[not_change_line] <= endline
                            ):
                                methods_delete_add[line_info] = (
                                    f"{startline}##{endline}##{funcname}"
                                )
                                methods_add_delete[
                                    f"{startline}##{endline}##{funcname}"
                                ] = line_info

            # 找到只有新增行没有删除行的方法
            for line_info in methods_add_delete.keys():
                # 并非只有新增行没有删除行的函数
                if methods_add_delete[line_info] != "":
                    continue
                st = int(line_info.split("##")[0])
                ed = int(line_info.split("##")[1])
                not_change_line = -1
                for line in range(st, ed + 1):
                    if line in new_old_map.keys():
                        not_change_line = line
                        break
                # 完全新增函数
                if not_change_line == -1:
                    continue
                for result in pre_file_methods:
                    if result == "" or result == " " or result == "\n":
                        continue

                    funcname = result.split("\t")[0]
                    if len(result.split("\t")) < 7:
                        continue
                    if (
                        result.split("\t")[3] == "f"
                        and "function:" not in result.split("\t")[5]
                        and "function:" not in result.split("\t")[6]
                        and "end:" in result.split("\t")[-1]
                    ):
                        startline = int(result.split("\t")[4].replace("line:", ""))
                        endline = int(result.split("\t")[-1].replace("end:", ""))
                        if (
                            new_old_map[not_change_line] >= startline
                            and new_old_map[not_change_line] <= endline
                        ):
                            methods_add_delete[line_info] = (
                                f"{startline}##{endline}##{funcname}"
                            )
                            methods_delete_add[
                                f"{startline}##{endline}##{funcname}"
                            ] = line_info

            before_method_code = ""
            after_method_code = ""
            for line_info in methods_delete_add.keys():
                # 完全删除的函数
                if methods_delete_add[line_info] == "":
                    continue
                st = int(line_info.split("##")[0])
                ed = int(line_info.split("##")[1])
                method_name = line_info.split("##")[2]
                before_file_code = pre_file_code.split("\n")
                after_file_code = post_file_code.split("\n")
                before_method_code = "\n".join(before_file_code[st - 1 : ed])
                st_after = int(methods_delete_add[line_info].split("##")[0])
                ed_after = int(methods_delete_add[line_info].split("##")[1])
                after_method_code = "\n".join(after_file_code[st_after - 1 : ed_after])
                method = {
                    "filename": f"{filename}#{method_name}#{st}#{ed+1}",
                    "before_file_code": pre_file_code,
                    "before_func_code": before_method_code,
                    "after_file_code": post_file_code,
                    "after_func_code": after_method_code,
                }
                method_info.append(method)
        except Exception as e:
            print(commit_id, "parse commit error!", e)
            return []
    return method_info


def get_modified_map(modified_file_code: str, modified_lines: list, filename: str):
    fp = open(filename, "w")
    fp.write(modified_file_code)
    fp.close()
    try:
        finding_cfiles = subprocess.check_output(
            CTAGS_PATH + " --fields=+ne -o - --sort=no " + filename,
            stderr=subprocess.STDOUT,
            shell=True,
        ).decode(errors="ignore")
        alllist = str(finding_cfiles)
        delete_lines = modified_lines.copy()
        temp_delete_lines = modified_lines.copy()
        modified_map = {}
        for result in alllist.split("\n"):
            if result == "" or result == " " or result == "\n":
                continue

            funcname = result.split("\t")[0]
            if len(result.split("\t")) < 7:
                continue

            if (
                result.split("\t")[3] == "f"
                and "function:" not in result.split("\t")[5]
                and "function:" not in result.split("\t")[6]
                and "end:" in result.split("\t")[-1]
            ):
                startline = int(result.split("\t")[4].replace("line:", ""))
                endline = int(result.split("\t")[-1].replace("end:", ""))
                for line in temp_delete_lines:
                    if line >= startline and line <= endline:
                        pure_del = True
                        for l in range(startline, endline + 1):
                            if l in modified_lines:
                                delete_lines.remove(l)
                            else:
                                pure_del = False
                        # 该方法是modified，并非是deleted
                        if not pure_del:
                            modified_map[
                                str(startline) + "##" + str(endline) + "##" + funcname
                            ] = ""
                        break
                temp_delete_lines = delete_lines.copy()
                if delete_lines == []:
                    break
        os.remove(filename)
        return modified_map, alllist.split("\n")
    except subprocess.CalledProcessError as e:
        print(e)
        os.remove(filename)
        return {}, []
    except:
        print("func parsing error..")
        os.remove(filename)
        return {}, []


def get_old_new_map(info: dict):
    new_old_map = {}
    old_new_map = {}
    delete_lines = info["delete"]
    add_lines = info["add"]
    delete = 1
    add = 1
    for i in range(1, 100000):
        while delete in delete_lines:
            delete += 1
        while add in add_lines:
            add += 1
        old_new_map[delete] = add
        new_old_map[add] = delete
        delete += 1
        add += 1
    return new_old_map, old_new_map


def extractor(
    repo_path: str, origin_commit: str, target_commit: str
) -> dict[str, dict]:
    origin_method_info = extract_commit_contents(repo_path, origin_commit)
    # print(origin_method_info)
    # print_methods_clearly(origin_method_info)
    methods = {}
    for method in origin_method_info:
        # print("method=======", method)
        file_path = method["filename"].split("#")[0]
        file_name = file_path.split("/")[-1]
        method_name = method["filename"].split("#")[1]
        file_code = get_file_content_at_commit(repo_path, target_commit, file_path)
        # print("file_code=======", file_code)
        if file_code is None:
            continue
        file_code = format.format_and_del_comment_c_cpp(file_code)
        method_code = get_method_code(
            file_code, file_path.replace("/", "_"), method_name
        )
        # print("method_code=======", method_code)
        if method_code == "":
            continue
        salt = hashlib.md5(method["before_func_code"].encode()).hexdigest()[:4]
        methods[f"{file_name}#{method_name}#{salt}"] = {
            "pa": method["before_func_code"],
            "pb": method["after_func_code"],
            "px": method_code,
        }
    return methods


def print_methods_clearly(methods):
    """
    清晰地打印方法信息，避免转义字符
    """
    print("=" * 80)
    print(f"提取到的方法信息 (共 {len(methods)} 个函数):")
    print("=" * 80)
    
    for i, (method_id, method_data) in enumerate(methods.items(), 1):
        print(f"\n[{i}/{len(methods)}] 方法ID: {method_id}")
        print("-" * 60)
        
        print("修改前的代码 (pa):")
        print(method_data['pa'])
        print("\n修改后的代码 (pb):")
        print(method_data['pb'])
        print("\n目标提交中的代码 (px):")
        print(method_data['px'])
        print("=" * 60)


if __name__ == "__main__":
    # 0aadcc3317e37789ff8cd4d8ae4de4e79e292034 6.6
    # f566c57f38ca6961da285a967d17688646010855 5.10
    # origin_commit = "1edb00c58f8a6875fad6a497aa2bacf37f9e6cd5"
    # target_commit = "94eb6858efecc1b4f02d8a6bd35e149f55c814c8"
    origin_commit = "7657f52afa43c680d9f66e7f184a20bf7c17bd9f"
    target_commit = "02b92fef1fd47273ff2c7286517ded7e488f6f07"
    repo_path = "/home/liping/patch-work/kernel"
    result = extractor(repo_path, origin_commit, target_commit)
    
    # 使用清晰的打印方式
    print_methods_clearly(result)
