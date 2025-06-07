from pydantic import Field
from typing import Union, Optional, List
from mcp.server.fastmcp import FastMCP
import subprocess
import json
import argparse
import os
import yaml
from pathlib import Path
from typing import Dict, Any

mcp = FastMCP("ccbMcp")

global_config = {
    'HOME_DIR': None,
    'GATEWAY_IP': None,
    'GATEWAY_PORT': None,
    'GITEE_ID': None,
    'GITEE_PASSWORD': None,
    'ACCOUNT': None,
    'PASSWORD': None,
    'OAUTH_TOKEN_URL': None,
    'OAUTH_REDIRECT_URL': None,
    'PUBLIC_KEY_URL': None,
    'SRV_HTTP_REPOSITORIES_HOST': None,
    'SRV_HTTP_REPOSITORIES_PORT': None,
    'SRV_HTTP_REPOSITORIES_PROTOCOL': None,
    'SRV_HTTP_RESULT_PROTOCOL': None,
    'SRV_HTTP_RESULT_HOST': None,
    'SRV_HTTP_RESULT_PORT': None,
    'DAG_HOST': None,
    'DAG_PORT': None
}

def _generate_build_targets(
    os_variant: Union[str, List[str]],
    architecture: Union[str, List[str]]
) -> List[Dict[str, str]]:
    """生成构建目标配置
    
    支持三种场景:
    1. 单环境多架构 (os_variant是字符串，architecture是列表)
    2. 多环境多架构 (os_variant和architecture都是列表)
    3. 单环境单架构 (都是字符串)
    """
    build_targets = []
    
    # 场景1: 单环境多架构
    if isinstance(os_variant, str) and isinstance(architecture, list):
        for arch in architecture:
            build_targets.append({
                "os_variant": os_variant,
                "architecture": arch
            })
    # 场景2: 多环境多架构
    elif isinstance(os_variant, list) and isinstance(architecture, list):
        for os_var, arch in zip(os_variant, architecture):
            build_targets.append({
                "os_variant": os_var,
                "architecture": arch
            })
    # 场景3: 单环境单架构
    else:
        build_targets.append({
            "os_variant": os_variant,
            "architecture": architecture
        })
    
    return build_targets

def _run_command(
    cmd: List[str],
    tmp_file: Optional[str] = None # 临时文件，命令执行完毕后会清理
) -> Dict[str, Any]:
    """执行命令并统一的公共函数"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env=env
        )
        return {"result": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"error": f"命令执行失败: {e.stderr.strip()}"}
    except Exception as e:
        return {"error": f"未知错误: {str(e)}"}
    finally:
        if tmp_file and os.path.exists(tmp_file):
            os.remove(tmp_file)
        
@mcp.tool()
def select_projects(
    os_project: Optional[str] = Field(default=None, description="工程名"),
    owner: Optional[str] = Field(default=None, description="过滤条件: 项目负责人"),
    fields: Optional[List[str]] = Field(default=None, description="指定返回的字段列表"),
    sort: Optional[List[str]] = Field(default=None, description="排序规则，格式为'字段名:asc|desc'")
) -> Dict[str, Any]:
    """查询EulerMaker中的工程信息（project）
    
    示例用法:
    1. 查看名为lly-test的EulerMaker工程信息
    2. 查看名为lly-test的EulerMaker工程信息，请返回os_project,users字段
    3. 请查询owner为xxx的所有工程，按照create_time降序排

    ccb命令：
    1. 查询所有projects: ccb select projects，数据量较大，不推荐，尽量带过滤条件查询
    2. 条件查询: ccb select projects os_project=openEuler:Mainline owner=xxx
    3. 指定字段: ccb select projects os_project=openEuler:Mainline --field os_project,users
    4. 排序: ccb select projects os_project=openEuler:Mainline --sort create_time:desc,os_project:asc
    """
    cmd = ["ccb", "select", "projects"]

    if os_project:
        cmd.append(f"os_project={os_project}")
    if owner:
        cmd.append(f"owner={owner}")

    if fields:
        cmd.extend(["--field", ",".join(fields)])

    if sort:
        cmd.extend(["--sort", ",".join(sort)])

    return _run_command(cmd)

@mcp.tool()
def select_snapshots(
    os_project: Optional[str] = Field(default=None, description="工程名"),
    snapshot_id: Optional[str] = Field(default=None, description="快照ID"),
    fields: Optional[List[str]] = Field(default=None, description="指定返回的字段列表"),
    sort: Optional[List[str]] = Field(default=None, description="排序规则，格式为'字段名:asc|desc'")
) -> Dict[str, Any]:
    """查询快照(snapshot)
    
    示例用法:
    1. 查询lly-test工程的所有快照
    2. 查询快照id为ce4e7a42-3167-11f0-bae2-02291c731353对应的工程名
    3. 查询lly-test工程的所有快照，按照create_time降序排

    ccb命令：
    1. 列出工程所有快照: ccb select snapshots os_project=openEuler:Mainline
    2. 通过快照ID查询: ccb select snapshots snapshot_id=ce4e7a42-3167-11f0-bae2-02291c731353 --field os_project
    3. 排序查询: ccb select snapshots os_project=openEuler:Mainline --sort create_time:desc
    """
    if not os_project and not snapshot_id:
        return {"error": "必须提供os_project或snapshot_id参数"}
    
    cmd = ["ccb", "select", "snapshots"]
    if os_project:
        cmd.append(f"os_project={os_project}")
    elif snapshot_id:
        cmd.append(f"snapshot_id={snapshot_id}")

    if fields:
        cmd.extend(["--field", ",".join(fields)])

    if sort:
        cmd.extend(["--sort", ",".join(sort)])
    
    return _run_command(cmd)

@mcp.tool()
def select_builds(
    build_id: Optional[str] = Field(default=None, description="构建ID"),
    os_project: Optional[str] = Field(default=None, description="工程名"),
    fields: Optional[List[str]] = Field(default=None, description="指定返回的字段列表")
) -> Dict[str, Any]:
    """查询EulerMaker中的构建任务（builds）
    
    示例用法:
    1. 查询build_id为cfa874d6-2f11-11f0-a00b-eaafa4f3ec35的构建任务
    2. 查询工程lly-test所有构建任务

    ccb命令：
    1. 指定返回字段: ccb select builds -f repo_id
    2. 按构建ID查询: ccb select builds build_id=cfa874d6-2f11-11f0-a00b-eaafa4f3ec35
    3. 按工程名查询: ccb select builds os_project=lly-test
    4. 组合查询: ccb select builds os_project=lly-test -f build_id,build_type
    """
    if not build_id and not os_project and not fields:
        return {"error": "必须提供build_id或os_project或fields参数"}
      
    cmd = ["ccb", "select", "builds"]

    if build_id:
        cmd.append(f"build_id={build_id}")
    if os_project:
        cmd.append(f"os_project={os_project}")

    if fields:
        cmd.extend(["--field", ",".join(fields)])
      
    return _run_command(cmd)
    
@mcp.tool()
def create_project(
    project_name: str = Field(..., description="要创建的工程名称"),
    json_config: Optional[str] = Field(default=None, description="JSON配置文件路径"),
    description: Optional[str] = Field(default=None, description="工程描述，如果未指定则和工程名一致"),
    spec_name: Optional[Union[str, List[str]]] = Field(default=None, description="包名或包名列表"),
    spec_url: Optional[Union[str, List[str]]] = Field(default=None, description="包git仓库URL或URL列表"),
    spec_branch: Optional[Union[str, List[str]]] = Field(default="master", description="包分支或分支列表"),
    os_variant: Optional[Union[str, List[str]]] = Field(default=None, description="构建环境或环境列表"),
    architecture: Optional[Union[str, List[str]]] = Field(default=None, description="架构类型或架构列表")
) -> Dict[str, Any]:
    """创建EulerMaker工程
     
    示例用法:
    1. 请创建一个EulerMaker工程，名为test
    2. 请根据配置文件/tmp/config.json来创建一个名为test的EulerMaker工程
    3. 创建一个名为0514的工程，里面有包gcc（url为https://gitee.com/src-openeuler/gcc.git ，分支为openEuler-20.03-LTS）
    以及包python-flask（https://gitee.com/src-openeuler/python-flask.git ），构建环境为openEuler:24.03-LTS-SP1，架构x86_64和aarch64

    ccb命令：
    1. 基本创建: ccb create projects test-project
    2. 使用JSON配置创建: ccb create projects test-project --json config.json
    """
    cmd = ["ccb", "create", "projects", project_name]

    if json_config:
        cmd.extend(["--json", json_config])
        return _run_command(cmd)

    if not (spec_name or os_variant or architecture):
        return _run_command(cmd)

    config_data = {
        "os_project": project_name,
        "description": description if description else project_name
    }
    
    # 处理包信息
    if spec_name and spec_url:
        if isinstance(spec_name, str):
            config_data["my_specs"] = [{
                "spec_name": spec_name,
                "spec_url": spec_url,
                "spec_branch": spec_branch
            }]
        else:
            config_data["my_specs"] = []
            for i, name in enumerate(spec_name):
                config_data["my_specs"].append({
                    "spec_name": name,
                    "spec_url": spec_url[i] if isinstance(spec_url, list) else spec_url,
                    "spec_branch": spec_branch[i] if isinstance(spec_branch, list) else spec_branch
                })
    
    # 处理构建目标
    if os_variant and architecture:
        config_data["build_targets"] = _generate_build_targets(os_variant, architecture)
    
    tmp_json_path = "/tmp/create_project_config.json"
    with open(tmp_json_path, 'w') as f:
        json.dump(config_data, f, indent=4)
    
    cmd.extend(["--json", tmp_json_path])
    return _run_command(cmd, tmp_json_path)

@mcp.tool()
def update_project(
    project_name: str = Field(..., description="要更新的工程名称"),
    json_config: Optional[str] = Field(default=None, description="JSON配置文件路径"),
    package_name: Optional[Union[str, List[str]]] = Field(default=None, description="包名或包名列表"),
    package_url: Optional[Union[str, List[str]]] = Field(default=None, description="包git仓库URL或URL列表"),
    package_branch: Optional[Union[str, List[str]]] = Field(default="master", description="包分支或分支列表"),
    users_to_remove: Optional[List[str]] = Field(default=None, description="要删除权限的用户列表"),
    users_to_add: Optional[Dict[str, str]] = Field(default=None, description="要添加的用户及角色，格式: {'username': 'role'}")
) -> Dict[str, Any]:
    """更新EulerMaker工程
    
    示例用法:
    1. 请在lly515工程中添加以下包，每行信息分别为包名，url，分支名：
       gcc-for-openEuler，https://gitee.com/openeuler/gcc-for-openEuler.git，master，
       fstrm，https://gitee.com/src-openeuler/fstrm.git ，openEuler-20.03-LTS
    2. 请删除lly-test工程中的lly用户，为lcx150用户添加maintainer角色，为llyqq添加reader角色
    3. 请根据配置文件/tmp/update_project.json来更新名为test的EulerMaker工程

    ccb命令：
    1. 通过json配置更新: ccb update projects test-project --json config.json
    """

    if not (json_config or package_name or package_url or users_to_remove or users_to_add):
        return {"error": "命令执行失败: 未提供任何更新内容"}
    cmd = ["ccb", "update", "projects", project_name]
    update_data = {}
    tmp_json_path = None
    
    # 处理添加包的情况
    if package_name and package_url:
        if isinstance(package_name, str):
            update_data["my_specs+"] = [{
                "spec_name": package_name,
                "spec_url": package_url,
                "spec_branch": package_branch
            }]
        else:
            update_data["my_specs+"] = [
                {
                    "spec_name": name,
                    "spec_url": package_url[i] if isinstance(package_url, list) else package_url,
                    "spec_branch": package_branch[i] if isinstance(package_branch, list) else package_branch
                }
                for i, name in enumerate(package_name)
            ]
    
    # 处理用户权限变更
    if users_to_remove or users_to_add:
        if users_to_remove:
            update_data["users-"] = users_to_remove
        if users_to_add:
            update_data["users+"] = users_to_add
    
    if update_data:  
        tmp_json_path = "/tmp/update_project.json"
        with open(tmp_json_path, 'w') as f:
            json.dump(update_data, f)
        cmd.extend(["--json", tmp_json_path])
    elif json_config:  
        cmd.extend(["--json", json_config])
    
    return _run_command(cmd, tmp_file=tmp_json_path)

@mcp.tool()
def set_package_lock(
    project_name: str = Field(..., description="工程名称"),
    package_name: str = Field(..., description="要操作的包名"),
    action: str = Field(..., description="操作类型: lock(锁定)或unlock(解锁)")
) -> Dict[str, Any]:
    """设置包的锁定状态
    
    示例用法:
    1. 锁定lly-test工程中的gcc包
    2. 解锁lly-test工程中的gcc包
    
    ccb命令：
    1. 锁定: ccb update projects test-project package_overrides.gcc.lock=true
    2. 解锁: ccb update projects test-project package_overrides.gcc.lock=false
    """
    if action not in ["lock", "unlock"]:
        return {"error": "action参数必须是lock或unlock"}
    
    lock_str = "true" if action == "lock" else "false"
    cmd = ["ccb", "update", "projects", project_name, f"package_overrides.{package_name}.lock={lock_str}"]
    return _run_command(cmd)

@mcp.tool()
def build_single_package(
    os_project: str = Field(..., description="要构建的工程名称"),
    package_name: str = Field(..., description="要构建的包名"),
    json_config: Optional[str] = Field(default=None, description="JSON配置文件路径，指定构建目标"),
    os_variant: Optional[Union[str, List[str]]] = Field(default=None, description="构建环境或环境列表"),
    architecture: Optional[Union[str, List[str]]] = Field(default=None, description="架构类型或架构列表")
) -> Dict[str, Any]:
    """执行单包构建，并返回查看构建任务状态的链接
    
    示例用法:
    1. 请构建lly-test工程中的fstrm包
    2. 请根据配置文件/tmp/build_targets.json构建lly-test工程中的fstrm包
    3. 请构建工程lly-test中的fstrm包，构建环境为openEuler:24.03-LTS-SP2，架构x86_64和aarch64
    
    ccb命令:
    1. 基本构建: ccb build-single os_project=test-project packages=gcc
    2. 使用JSON配置构建: 
       ccb build-single os_project=test-project packages=gcc --json build_targets.json
    """

    cmd = ["ccb", "build-single", f"os_project={os_project}", f"packages={package_name}"]
    result = {"error": "未知错误"}
    
    if os_variant and architecture:
        # 生成构建目标配置
        build_targets = _generate_build_targets(os_variant, architecture)
        config_data = {"build_targets": build_targets}
        
        tmp_json_path = "/tmp/build_targets.json"
        with open(tmp_json_path, 'w') as f:
            json.dump(config_data, f, indent=4)
        
        cmd.extend(["--json", tmp_json_path])
        result = _run_command(cmd, tmp_json_path)
    else:
        if json_config:
            cmd.extend(["--json", json_config])
        result = _run_command(cmd)
        
    if "error" in result:
        return result
        
    # 从全局配置获取OAUTH_REDIRECT_URL，并处理拼成查看构建任务状态的链接
    oauth_url = global_config['OAUTH_REDIRECT_URL']
    base_url = oauth_url.split('/oauth/')[0]
    build_result_url = f"{base_url}/package/build?osProject={os_project}&packageName={package_name}"
    
    return {
        "result": result.get("result", ""),
        "build_result_url": build_result_url
    }

@mcp.tool()
def build(
    build_type: str,  # 构建类型: full(全量)或incremental(增量)
    os_project: Optional[str] = None,  # 项目名称
    snapshot_id: Optional[str] = None,  # 快照ID
    build_targets: Optional[List[Dict[str, str]]] = None,  # 构建目标配置
    os_variant: Optional[Union[str, List[str]]] = None,  # 构建环境或环境列表
    architecture: Optional[Union[str, List[str]]] = None  # 架构类型或架构列表
) -> Dict[str, Any]:
    """执行全量或增量构建，并返回查看构建任务状态的链接，举例：
    https://eulermaker.compass-ci.openeuler.openatom.cn/package/build?osProject=test-project&buildId=cfa874d6-2f11-11f0-a00b-eaafa4f3ec35
    
    示例用法:
    1. 全量构建lly-test工程
    2. 请基于ce4e7a42-3167-11f0-bae2-02291c731353快照进行增量构建
    3. 全量构建lly-test工程，构建环境为openEuler:24.03-LTS-SP1，架构x86_64和aarch64

    ccb命令：
    1. 全量构建: ccb build os_project=test-project build_type=full
    2. 增量构建: ccb build snapshot_id=xxx build_type=incremental
    3. 使用JSON配置构建: 
       ccb build os_project=test-project build_type=full --json build_targets.json
    """

    if not os_project and not snapshot_id:
        return {"error": "必须提供os_project或snapshot_id参数"}
    
    if build_type not in ["full", "incremental"]:
        return {"error": "build_type必须是full或incremental"}
    
    cmd = ["ccb", "build", f"build_type={build_type}"]
    result = {"error": "未知错误"}
    
    if os_project:
        cmd.append(f"os_project={os_project}")
    if snapshot_id:
        cmd.append(f"snapshot_id={snapshot_id}")

    if os_variant and architecture:
        # 生成构建目标配置
        build_targets = _generate_build_targets(os_variant, architecture)
        config_data = {"build_targets": build_targets}
        
        tmp_json_path = "/tmp/build_targets.json"
        with open(tmp_json_path, 'w') as f:
            json.dump(config_data, f, indent=4)
        
        cmd.extend(["--json", tmp_json_path])
        result = _run_command(cmd, tmp_json_path)
    else:
        if build_targets:
            cmd.extend(["--json", build_targets])
        result = _run_command(cmd)
    if "error" in result:
        return result
        
    # 解析命令输出获取build_id
    output = json.loads(result.get("result", ""))
    build_id = next(iter(output.get("data", {}).keys())) if output.get("data") else None
    
    # 从全局配置获取OAUTH_REDIRECT_URL并处理
    oauth_url = global_config['OAUTH_REDIRECT_URL']
    base_url = oauth_url.split('/oauth/')[0]

    ret = {"result": result.get("result", "")}
    # 如果只提供了snapshot_id而没有os_project，则查询快照获取工程名
    if snapshot_id and not os_project:
        cmd = ["ccb", "select", "snapshots", f"snapshot_id={snapshot_id}", "--field", "os_project"]
        result = _run_command(cmd)
        
        try:
            snapshot_data = json.loads(result.get("result", "[]"))
            if (isinstance(snapshot_data, list) and
                len(snapshot_data) > 0 and
                isinstance(snapshot_data[0], dict) and
                "_source" in snapshot_data[0] and
                isinstance(snapshot_data[0]["_source"], dict)):
                # 提取第一个结果的os_project字段
                os_project = snapshot_data[0]["_source"].get("os_project")
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            # 如果获取os_project，静默跳过（不报错）
            pass
    
    # 构造构建结果URL
    if os_project:
        ret["build_result_url"] = f"{base_url}/project/build?osProject={os_project}" + (f"&buildId={build_id}" if build_id else "")
    
    
    return ret

@mcp.tool()
def download_package(
    os_project: Optional[str] = Field(default=None, description="项目名称"),
    snapshot_id: Optional[str] = Field(default=None, description="快照ID"),
    packages: str = Field(..., description="要下载的包名"),
    architecture: str = Field(..., description="架构类型，如aarch64,x86_64等"),
    dest: Optional[str] = Field(default=None, description="下载文件存放路径，默认为当前路径"),
    source: bool = Field(default=False, description="是否下载源码包(-s参数)"),
    debug: bool = Field(default=False, description="是否下载debug包(-d参数)"),
    subpackages: Optional[str] = Field(default=None, description="要下载的子包(-b参数)，支持'all'或逗号分隔的多个子包")
) -> Dict[str, Any]:
    """下载软件包
    
    示例用法:
    请下载lly-test中构建出来的fstrm的aarch64架构包，保存到/tmp目录

    ccb命令：
    1. 基本下载: 
       ccb download os_project=test-project packages=python-flask architecture=aarch64
    2. 指定下载路径:
       ccb download os_project=test-project packages=python-flask architecture=aarch64 dest=/tmp/rpm
    3. 使用快照ID:
       ccb download snapshot_id=123456 packages=python-flask architecture=aarch64
    4. 下载源码包:
       ccb download os_project=test-project packages=python-flask architecture=aarch64 -s
    5. 下载debug包:
       ccb download os_project=test-project packages=python-flask architecture=aarch64 -d
    6. 下载所有子包:
       ccb download os_project=test-project packages=python-flask architecture=aarch64 -b all
    7. 下载指定子包:
       ccb download os_project=test-project packages=python-flask architecture=aarch64 -b python2-flask
    8. 组合使用:
       ccb download os_project=test-project packages=python-flask architecture=aarch64 -b all -s -d
    """
    if not os_project and not snapshot_id:
        return {"error": "必须提供os_project或snapshot_id参数"}
    
    cmd = ["ccb", "download"]

    if os_project:
        cmd.append(f"os_project={os_project}")
    if snapshot_id:
        cmd.append(f"snapshot_id={snapshot_id}")
    
    cmd.append(f"packages={packages}")
    cmd.append(f"architecture={architecture}")
    
    if dest:
        cmd.append(f"dest={dest}")
    
    if source:
        cmd.append("-s")
    
    if debug:
        cmd.append("-d")

    if subpackages:
        cmd.extend(["-b", subpackages])
    
    return _run_command(cmd)

@mcp.tool()
def cancel(
    build_id: str = Field(..., description="要取消的构建任务ID")
) -> Dict[str, Any]:
    """取消构建任务
    
    示例用法:
    取消构建864db44a-3178-11f0-ba18-3ef950579dc9
    
    ccb命令：
    ccb cancel 864db44a-3178-11f0-ba18-3ef950579dc9
    """
    cmd = ["ccb", "cancel", build_id]
    
    return _run_command(cmd)

@mcp.tool()
def log(
    job_id: str = Field(..., description="要查看日志的job ID")
) -> Dict[str, Any]:
    """查看job日志
    
    示例用法:
    查看cbs.8843409的日志
    
    ccb命令：
    ccb log cbs.8843409
    """
    cmd = ["ccb", "log", job_id]
    
    return _run_command(cmd)

def init_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--HOME_DIR', required=True)
    parser.add_argument('--GATEWAY_IP', required=True)
    parser.add_argument('--GATEWAY_PORT', required=True)
    parser.add_argument('--GITEE_ID', required=True)
    parser.add_argument('--GITEE_PASSWORD', required=True)
    parser.add_argument('--ACCOUNT', required=True)
    parser.add_argument('--PASSWORD', required=True)
    parser.add_argument('--OAUTH_TOKEN_URL', required=True)
    parser.add_argument('--OAUTH_REDIRECT_URL', required=True)
    parser.add_argument('--PUBLIC_KEY_URL', required=True)
    parser.add_argument('--SRV_HTTP_REPOSITORIES_HOST', required=True)
    parser.add_argument('--SRV_HTTP_REPOSITORIES_PORT', required=True)
    parser.add_argument('--SRV_HTTP_REPOSITORIES_PROTOCOL', required=True)
    parser.add_argument('--SRV_HTTP_RESULT_PROTOCOL', required=True)
    parser.add_argument('--SRV_HTTP_RESULT_HOST', required=True)
    parser.add_argument('--SRV_HTTP_RESULT_PORT', required=True)
    parser.add_argument('--DAG_HOST', required=True)
    parser.add_argument('--DAG_PORT', required=True)
    
    args = parser.parse_args()

    global env, global_config
    env = dict(os.environ)
    env["HOME"] = args.HOME_DIR
    
    config_data = {
        'HOME_DIR': args.HOME_DIR,
        'GATEWAY_IP': args.GATEWAY_IP,
        'GATEWAY_PORT': args.GATEWAY_PORT,
        'GITEE_ID': args.GITEE_ID,
        'GITEE_PASSWORD': args.GITEE_PASSWORD,
        'ACCOUNT': args.ACCOUNT,
        'PASSWORD': args.PASSWORD,
        'OAUTH_TOKEN_URL': args.OAUTH_TOKEN_URL,
        'OAUTH_REDIRECT_URL': args.OAUTH_REDIRECT_URL,
        'PUBLIC_KEY_URL': args.PUBLIC_KEY_URL,
        'SRV_HTTP_REPOSITORIES_HOST': args.SRV_HTTP_REPOSITORIES_HOST,
        'SRV_HTTP_REPOSITORIES_PORT': args.SRV_HTTP_REPOSITORIES_PORT,
        'SRV_HTTP_REPOSITORIES_PROTOCOL': args.SRV_HTTP_REPOSITORIES_PROTOCOL,
        'SRV_HTTP_RESULT_PROTOCOL': args.SRV_HTTP_RESULT_PROTOCOL,
        'SRV_HTTP_RESULT_HOST': args.SRV_HTTP_RESULT_HOST,
        'SRV_HTTP_RESULT_PORT': args.SRV_HTTP_RESULT_PORT,
        'DAG_HOST': args.DAG_HOST,
        'DAG_PORT': args.DAG_PORT
    }
    global_config.update(config_data)
    
    # 确保配置目录存在
    config_dir = os.path.expanduser('~/.config/cli/defaults')
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    
    # 写入配置文件，如果文件已存在，会覆盖原有内容
    config_file = os.path.join(config_dir, 'config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f, default_flow_style=False)

if __name__ == "__main__":
    init_config()
    mcp.run()

