#!/usr/bin/env python3
from pydantic import Field
from typing import Optional
from mcp.server.fastmcp import FastMCP
import os
import re
import shutil
import datetime
from git import Repo, InvalidGitRepositoryError
from git.exc import GitCommandError
from git.config import GitConfigParser

mcp = FastMCP("patchMcp")

# 补丁类型在spec文件中匹配的定位符
start_patterns = {
    "loongarch": '%ifarch loongarch64',
    "sw64": '%ifarch sw_64',
    "common": '# patches for all arch'
}
end_patterns = {
    "loongarch": '%endif',
    "sw64": '%endif',
    "common": '\n\n'
}

@mcp.tool()
def apply_patch_to_repo(
    repo_path: str = Field(..., description="目标仓库路径"),
    patch_path: str = Field(..., description="patch文件路径"),
    patch_info: Optional[str] = Field(None, description="patch变更信息，用于changelog。如果未提供，则从patch文件名提取")
) -> dict:
    """将patch文件应用到仓库,并更新.spec文件"""
    try:
        if not (os.path.exists(repo_path) and os.path.exists(patch_path)):
            return {
                "status": "error",
                "code": "PATH_NOT_FOUND",
                "message": "仓库路径或patch文件不存在"
            }
        
        spec_files = [f for f in os.listdir(repo_path) if f.endswith('.spec')]
        if not spec_files:
            return {
                "status": "error",
                "code": "SPEC_NOT_FOUND",
                "message": f"未在仓库路径{repo_path}下找到.spec文件"
            }
        
        patch_name = os.path.basename(patch_path)
        dest_patch = os.path.join(repo_path, patch_name)
        
        # 如果未提供patch_info，则从文件名提取，移除.patch后缀
        if patch_info is None:
            patch_info = patch_name.replace('.patch', '')

        spec_path = os.path.join(repo_path, spec_files[0])
        spec_data = parse_spec_file(spec_path)
        
        if os.path.exists(dest_patch) and patch_name in spec_data['patch_files']:
            return {
                "status": "error",
                "code": "PATCH_ALREADY_APPLIED",
                "message": f"patch文件已存在且已记录到spec: {patch_name}",
                "patch_file": dest_patch,
                "spec_file": spec_path
            }
            
        # 复制patch文件到目标仓库
        shutil.copy2(patch_path, dest_patch)
        
        # 更新.spec文件
        try:
            updated_spec = update_spec_file(spec_path, spec_data, patch_name, patch_info, repo_path)
        except Exception as e:
            # 回滚已复制的patch文件
            if os.path.exists(dest_patch):
                os.remove(dest_patch)
            return {
                "status": "error",
                "code": "SPEC_UPDATE_FAILED",
                "message": str(e)
            }
        
        return {
            "status": "success",
            "patch_file": dest_patch,
            "spec_file": spec_path,
            "release_updated": True,
            "patch_added": True,
            "changelog_updated": True
        }
        
    except Exception as e:
        return {
            "status": "error",
            "code": "UNKNOWN_ERROR",
            "message": str(e)
        }

def get_patch_type(patch_name: str) -> str:
    """根据补丁文件名判断补丁类型
        "loongarch" - 龙芯架构补丁
        "sw64" - 申威架构补丁
        "common" - 通用补丁
    """
    patch_lower = patch_name.lower()
    if "loongarch" in patch_lower:
        return "loongarch"
    elif "sw64" in patch_lower or "sw_64" in patch_lower:
        return "sw64"
    return "common"

def parse_spec_file(spec_path: str) -> dict:
    """解析.spec文件内容"""
    with open(spec_path, 'r') as f:
        content = f.read()
    
    # 提取Release行
    release_num = 0
    release_var = None
    release_match = re.search(r'^Release:\s*%{(\w+)}', content, re.MULTILINE)
    if release_match:
        # 处理Release: %{var}格式
        release_var = release_match.group(1)
        var_def_match = re.search(r'^%global\s+' + release_var + r'\s+(\d+)', content, re.MULTILINE)
        if var_def_match:
            release_num = int(var_def_match.group(1))
    else:
        # 处理普通格式Release: 1
        release_match = re.search(r'^Release:\s*(\d+)', content, re.MULTILINE)
        release_num = int(release_match.group(1)) if release_match else 0
    
    # 提取changelog部分
    changelog_start = content.find('%changelog')
    changelog = content[changelog_start:] if changelog_start != -1 else ""

    version = parse_version_from_changelog(changelog)

    parse_result_dict = {
        'content': content,
        'release_num': release_num,
        'changelog': changelog,
        'version': version
    }

    # 从spec文件中解析已有patch相关的信息
    patch_info_dict = parse_patch_info_from_spec(content)
    parse_result_dict.update(patch_info_dict)

    return parse_result_dict

def update_spec_file(spec_path: str, spec_data: dict, patch_name: str, patch_info: str, repo_path: str) -> str:
    """
    更新.spec文件
        自动更新.spec文件中的Release版本号(+1)
        在.spec文件中按照补丁分类规则添加新的Patch行
        若.spec文件采用`%patch -P1 -p1`这样的命令来安装补丁，也会按照补丁分类规则，自动在对应部分生成安装新添加的补丁的命令
        生成标准化的changelog条目
    抛出:
        ValueError: 当patch已存在且已记录时
    """
    try:
        name, email = get_git_user_info(repo_path)
    except ValueError as e:
        return {
            "status": "error",
            "code": "GIT_USER_INFO_MISSING",
            "message": str(e) + "请配置git用户名和邮箱"
        }
    
    if patch_name in spec_data['patch_files']:
        raise ValueError(f"patch文件已应用到spec文件中: {patch_name}")

    # 更新Release行
    release_match = re.search(r'^Release:\s*%{(\w+)}', spec_data['content'], re.MULTILINE)
    if release_match:
        # 处理Release: %{var}格式
        release_var = release_match.group(1)
        var_def_match = re.search(r'^%global\s+' + release_var + r'\s+(\d+)', spec_data['content'], re.MULTILINE)
        if var_def_match:
            new_value = int(var_def_match.group(1)) + 1
            updated_content = re.sub(
                r'^%global\s+' + release_var + r'\s+\d+',
                f"%global {release_var} {new_value}",
                spec_data['content'],
                flags=re.MULTILINE
            )
    else:
        # 处理普通格式Release: 1
        new_release = f"Release:        {spec_data['release_num'] + 1}"
        updated_content = re.sub(
            r'^Release:\s*\d+',
            new_release,
            spec_data['content'],
            flags=re.MULTILINE
        )
    
    # 处理spec中的patch内容
    updated_content = update_patch_info(spec_data, patch_name, updated_content)

    # 生成标准化的changelog条目
    existing_changelog = spec_data['changelog'][len('%changelog'):].lstrip('\n')
    new_changelog_entry = f"""%changelog
* {datetime.datetime.now().strftime("%a %b %d %Y")} {name} <{email}> - {spec_data['version']}
- DESC: {patch_info}

{existing_changelog}"""
    
    updated_content = updated_content.replace(
        spec_data['changelog'],
        new_changelog_entry
    )
    
    with open(spec_path, 'w') as f:
        f.write(updated_content)
    
    return updated_content

def get_git_user_info(repo_path: str) -> tuple:
    """获取git用户信息，用户名和邮箱
    """
    try:
        repo = Repo(repo_path)
        with repo.config_reader() as config:
            name = config.get_value('user', 'name')
            email = config.get_value('user', 'email')
            if not name or not email:
                raise ValueError("Git用户信息未配置")
            return name, email
    except Exception as e:
        raise ValueError(f"获取Git用户信息失败: {str(e)}")

def parse_version_from_changelog(changelog: str) -> str:
    """从changelog中解析最新版本号"""
    version_match = re.search(r'-\s(\d+\.\d+\.\d+-\d+)', changelog)
    if version_match:
        version_parts = version_match.group(1).split('-')
        if len(version_parts) == 2:
            version_parts[1] = str(int(version_parts[1]) + 1)
            return '-'.join(version_parts)
    return "1.0.0-1"

def get_max_patch_in_section(section_start: int, section_end: int, content: str) -> int:
    """获取指定部分的最大补丁编号"""
    section_content = content[section_start:section_end]
    patch_matches = list(re.finditer(r'^Patch(\d+):', section_content, re.MULTILINE))
    return max(int(m.group(1)) for m in patch_matches) if patch_matches else 0

def parse_patch_info_from_spec(spec_content: str) -> dict:
    """从spec文件中解析已有patch相关的信息"""
    # 提取所有Patch行并检测格式（兼容.patch和.diff文件）
    patch_matches = list(re.finditer(r'^Patch(\d+):\s*(.+\.(?:patch|diff))', spec_content, re.MULTILINE))
    patch_nums = [int(m.group(1)) for m in patch_matches]
    patch_files = [m.group(2) for m in patch_matches]
    
    # 提取%patch指令
    patch_cmd_matches = list(re.finditer(r'^%patch\s+-P(\d+)\s+-p\d+', spec_content, re.MULTILINE))
    patch_cmd_nums = [int(m.group(1)) for m in patch_cmd_matches]
    last_patch_cmd_pos = patch_cmd_matches[-1].end() if patch_cmd_matches else None
    
    # 检测Patch格式 (带前导零或不带)和空格对齐方式
    patch_format = "Patch%d:"
    space_count = 6  # 默认6个空格
    if patch_matches:
        first_patch = patch_matches[0].group(0)
        patch_num_part = first_patch.split(':')[0]
        if patch_num_part.startswith('Patch0') and len(patch_num_part) > 5:  # 检测前导零
            patch_format = "Patch%04d:"
        else:
            patch_format = "Patch%d:"
        
        # 精确提取原有格式中的空格数量
        space_count = len(first_patch.split(':')[1]) - len(first_patch.split(':')[1].lstrip())
    
    # 获取各架构的补丁最大编号
    section_max = {
        'common': 0,
        'loongarch': 0,
        'sw64': 0
    }
    for section in section_max.keys():
        section_start = spec_content.find(start_patterns[section])
        if section_start != -1:
            section_end = spec_content.find(end_patterns[section], section_start)
            if section_end == -1:
                section_end = len(spec_content)
            section_max[section] = get_max_patch_in_section(section_start, section_end, spec_content)

    # 解析spec文件在打补丁时是否区分架构,如果含有loongarch或sw64的patch部分，就代表区分架构
    # 根据是否区分架构，计算下一个Patch编号
    if section_max['loongarch'] + section_max['sw64']:
        is_spec_arch_related = True
        all_nums = list(section_max.values()) + patch_cmd_nums
        max_patch = max(all_nums) if all_nums else 0
        next_patch_num = max_patch + 1
    else:
        is_spec_arch_related = False
        # 取Patch行和%patch指令中的最大编号+1
        all_patch_nums = patch_nums + patch_cmd_nums
        next_patch_num = max(all_patch_nums) + 1 if all_patch_nums else 1
    
    # 获取最后一个Patch行的位置
    last_patch_pos = patch_matches[-1].end() if patch_matches else None

    patch_info_dict = {
        'patch_nums': patch_nums,
        'patch_files': patch_files,
        'next_patch_num': next_patch_num,
        'last_patch_pos': last_patch_pos,
        'has_patches': bool(patch_matches),
        'patch_format': patch_format,
        'has_patch_cmds': bool(patch_cmd_matches),
        'last_patch_cmd_pos': last_patch_cmd_pos,
        'space_count': space_count,
        'is_spec_arch_related': is_spec_arch_related,
        'section_max': {
            'common': section_max['common'],
            'loongarch': section_max['loongarch'],
            'sw64': section_max['sw64']
        }
    }

    return patch_info_dict

def update_patch_for_arch_related(spec_data: dict, patch_name: str, patch_format: str, space_count: int, updated_content: str) -> str:
    """在区分架构的spec文件中更新补丁信息"""
    patch_type = get_patch_type(patch_name)

    next_num = spec_data['section_max'][patch_type] + 1
    patch_line = generate_patch_line(next_num, patch_format, space_count, patch_name)

    patches_end = 0
    find_start_pattern = start_patterns[patch_type]
    find_end_pattern = end_patterns[patch_type]
    # 查找patch_type部分
    patch_type_start = updated_content.find(find_start_pattern)
    if patch_type_start != -1:
        # 查找该部分的最后一个Patch行
        patch_type_end = updated_content.find(find_end_pattern, patch_type_start)
        patch_matches = list(re.finditer(r'^Patch(\d+):\s*(.+\.(?:patch|diff))',
                                        updated_content[patch_type_start:patch_type_end],
                                        re.MULTILINE))
        if patch_matches:
            # 获取该部分最大的Patch编号
            max_patch_num = max(int(m.group(1)) for m in patch_matches)
            last_patch_match = next(m for m in patch_matches if int(m.group(1)) == max_patch_num)
            insert_pos = patch_type_start + last_patch_match.end()
        else:
            # 没有Patch行，在patch_type后插入
            insert_pos = patch_type_start + len(find_start_pattern)
    else:
        # 没有patch_type_start部分，在通用补丁后插入
        insert_pos = spec_data['last_patch_pos']
    patches_end = insert_pos
    
    # 检查是否需要换行
    if not updated_content[insert_pos:insert_pos+1] == '\n':
        updated_content = updated_content[:insert_pos] + '\n' + updated_content[insert_pos:]
        insert_pos += 1
    
    updated_content = (
        updated_content[:insert_pos] +
        f"\n{patch_line}" +
        updated_content[insert_pos:]
    )
    
    # 处理%patch指令
    if spec_data['has_patch_cmds'] and 'last_patch_cmd_pos' in spec_data:
        patch_num = next_num
        find_start_pattern = start_patterns[patch_type]
        find_end_pattern = end_patterns[patch_type]
        # 查找patch_type部分
        patch_type_start = updated_content.find(find_start_pattern,patches_end)
        if patch_type_start != -1:
            patch_type_end = updated_content.find(find_end_pattern, patch_type_start)
            
            # 查找该部分的所有%patch命令
            patch_cmd_matches = list(re.finditer(r'^(\s*)%patch\s+-P(\d+)\s+-p\d+\s*$',
                                                updated_content[patch_type_start:patch_type_end],
                                                re.MULTILINE))
            
            # :q在最后一个%patch命令后插入新命令
            if patch_cmd_matches:
                last_cmd_match = patch_cmd_matches[-1]
                indent = last_cmd_match.group(1)
                insert_pos = patch_type_start + last_cmd_match.end()
                
                # 移动到行尾
                while insert_pos < patch_type_end and updated_content[insert_pos] != '\n':
                    insert_pos += 1
                
                new_patch_cmd = f"\n{indent}%patch -P{patch_num} -p1\n"
            else:
                # 没有%patch命令，在patch_type后插入
                insert_pos = patch_type_start + len(find_start_pattern)
                new_patch_cmd = f"\n    %patch -P{patch_num} -p1\n"
            
            updated_content = (
                updated_content[:insert_pos] +
                new_patch_cmd +
                updated_content[insert_pos:]
            )
    return updated_content

def update_patch_for_arch_unrelated(spec_data: dict, patch_name: str, patch_format: str, space_count: int, updated_content: str) -> str:
    """在不区分架构的spec文件中，更新补丁信息"""
    next_num = spec_data['next_patch_num']
    patch_line = generate_patch_line(next_num, patch_format, space_count, patch_name)

    # 找到所有Patch行并按编号排序（兼容.patch和.diff文件）
    patch_matches = list(re.finditer(r'^Patch(\d+):\s*(.+\.(?:patch|diff))', updated_content, re.MULTILINE))
    if patch_matches:
        patch_nums = [int(m.group(1)) for m in patch_matches]
        max_patch_num = max(patch_nums)
        
        # 找到编号最大的Patch行
        last_patch_match = next(m for m in patch_matches if int(m.group(1)) == max_patch_num)
        last_patch_line = last_patch_match.group(0)
        
        insert_pos = last_patch_match.end()
        
        # 检查是否需要换行
        if not updated_content[insert_pos:insert_pos+1] == '\n':
            updated_content = updated_content[:insert_pos] + '\n' + updated_content[insert_pos:]
            insert_pos += 1
        
        updated_content = (
            updated_content[:insert_pos] +
            f"\n{patch_line}" +
            updated_content[insert_pos:]
        )
    
    # 处理%patch指令
    if spec_data['has_patch_cmds']:
        patch_cmd_matches = list(re.finditer(r'^(\s*)%patch\s+-P(\d+)\s+-p\d+', updated_content, re.MULTILINE))
        if patch_cmd_matches:
            # 获取最后一个%patch指令的位置和缩进
            last_cmd_num = max(int(m.group(2)) for m in patch_cmd_matches)
            last_cmd_match = next(m for m in patch_cmd_matches if int(m.group(2)) == last_cmd_num)
            indent = last_cmd_match.group(1)
            last_cmd_pos = last_cmd_match.end()
            
            # 插入新%patch指令，保持正确缩进和换行
            updated_content = (
                updated_content[:last_cmd_pos] +
                f"\n{indent}%patch -P{spec_data['next_patch_num']} -p1\n" +
                updated_content[last_cmd_pos:]
            )

    return updated_content

def update_patch_info(spec_data: dict, patch_name: str, updated_content: str) -> str:
    """更新spec文件中的补丁信息"""
    # 添加Patch行，使用检测到的格式和空格数量
    patch_format = spec_data.get('patch_format', 'Patch%d:')
    space_count = spec_data.get('space_count', 6)
    
    if spec_data['has_patches']:
        if spec_data['is_spec_arch_related']:
            updated_content = update_patch_for_arch_related(spec_data, patch_name, patch_format, space_count, updated_content)
        else:
            updated_content = update_patch_for_arch_unrelated(spec_data, patch_name, patch_format, space_count, updated_content)
    else:
        next_num = spec_data['next_patch_num']
        patch_line = generate_patch_line(next_num, patch_format, space_count, patch_name)
        # 在BuildRoot和Source之间添加
        buildroot_pos = updated_content.find('BuildRoot:')
        source_pos = updated_content.find('Source:', buildroot_pos)
        if buildroot_pos != -1 and source_pos != -1:
            updated_content = (
                updated_content[:source_pos] +
                f"\n{patch_line}" +
                updated_content[source_pos:]
            )
    return updated_content

def generate_patch_line(next_num: int, patch_format: str, space_count: int, patch_name: str) -> str:
    """生成格式化的补丁行"""
    if patch_format.startswith('Patch%04d'):
        return f"Patch{next_num:04d}:" + " " * space_count + patch_name
    else:
        return f"Patch{next_num}:" + " " * space_count + patch_name

if __name__ == "__main__":
    mcp.run()