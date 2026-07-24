import tarfile
import os
import subprocess
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tar压缩和解压工具")

def safe_extract(tar: tarfile.TarFile, output_dir: str) -> None:
    """安全解压tar文件，防止路径遍历攻击
    
    Args:
        tar: TarFile对象
        output_dir: 解压目标目录
        
    Raises:
        ValueError: 当检测到不安全的成员时抛出
    """
    output_path = Path(output_dir).resolve()
    
    # 确保输出目录存在
    output_path.mkdir(parents=True, exist_ok=True)
    
    for member in tar.getmembers():
        # 1. 跳过绝对路径和包含..的路径
        if member.name.startswith('/') or '..' in member.name.split(os.sep):
            raise ValueError(f"不安全的路径名: {member.name}")
        
        # 2. 跳过设备文件、软链接、硬链接
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError(f"不支持的文件类型: {member.name} (类型: {member.type})")
        
        # 3. 计算最终落点路径
        target_path = output_path / member.name
        
        # 4. 再次检查解析后的路径是否在输出目录内
        try:
            target_path.resolve().relative_to(output_path)
        except ValueError:
            raise ValueError(f"路径逃逸检测失败: {member.name} -> {target_path}")
        
        # 5. 如果父目录不存在，创建父目录
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 6. 提取文件（只提取普通文件和目录）
        if member.isfile() or member.isdir():
            tar.extract(member, output_path, set_attrs=False)
        else:
            raise ValueError(f"不支持的文件类型: {member.name} (类型: {member.type})")

def validate_path_component(path_str: str) -> str:
    """验证路径组件是否安全
    
    Args:
        path_str: 路径字符串
        
    Returns:
        规范化后的路径字符串
        
    Raises:
        ValueError: 路径不安全时抛出
    """
    # 禁止空字符串
    if not path_str:
        raise ValueError("路径不能为空")
    
    # 禁止绝对路径
    if path_str.startswith('/'):
        raise ValueError("路径不能是绝对路径")
    
    # 禁止包含..路径遍历
    if '..' in path_str.split(os.sep):
        raise ValueError("路径不能包含 '..'")
    
    # 禁止包含特殊字符（允许字母、数字、下划线、点、连字符、正斜杠）
    import re
    # 允许的字符：字母数字、下划线、点、连字符、正斜杠、空格
    if not re.match(r'^[a-zA-Z0-9_\-./\s]+$', path_str):
        raise ValueError(f"路径包含非法字符: {path_str}")
    
    # 禁止路径过长（防止DoS）
    if len(path_str) > 4096:
        raise ValueError("路径长度超过限制")
    
    return path_str

@mcp.tool()
def create_tar(source_path: str, output_path: str) -> str:
    """将文件或目录打包为tar.gz压缩包
    
    Args:
        source_path: 要压缩的文件或目录路径
        output_path: 输出的tar.gz文件路径
        
    Returns:
        操作结果信息
    """
    try:
        # 验证并规范化路径
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        
        # 验证源路径存在
        if not source.exists():
            return f"错误: 源路径不存在: {source_path}"
        
        # 确保输出目录存在
        output.parent.mkdir(parents=True, exist_ok=True)
        
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(source_path, arcname=os.path.basename(source_path))
        return f"成功创建压缩包: {output_path}"
    except Exception as e:
        return f"创建压缩包失败: {str(e)}"

@mcp.tool()
def extract_tar(tar_path: str, output_dir: str) -> str:
    """安全解压tar.gz压缩包到指定目录
    
    包含安全校验：
    - 防止路径遍历攻击（../、绝对路径）
    - 禁止软/硬链接、设备文件等危险类型
    - 路径安全验证
    
    Args:
        tar_path: 要解压的tar.gz文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        # 验证并规范化路径
        tar_path_obj = Path(tar_path).resolve()
        if not tar_path_obj.exists():
            return f"错误: 压缩包不存在: {tar_path}"
        
        output_path = Path(output_dir).resolve()
        
        # 验证输出目录路径
        validate_path_component(output_dir)
        
        output_path.mkdir(parents=True, exist_ok=True)
        
        with tarfile.open(tar_path) as tar:
            safe_extract(tar, output_dir)
        
        return f"成功安全解压到目录: {output_dir}"
    except ValueError as e:
        return f"安全检查失败: {str(e)}"
    except Exception as e:
        return f"解压失败: {str(e)}"

@mcp.tool()
def rpm_unpack(rpm_path: str, output_dir: str) -> str:
    """解压RPM包到指定目录
    
    使用参数数组调用subprocess，防止命令注入。
    
    Args:
        rpm_path: RPM文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        # 验证并规范化路径
        rpm_path_obj = Path(rpm_path).resolve()
        if not rpm_path_obj.exists():
            return f"错误: RPM文件不存在: {rpm_path}"
        
        # 验证输出目录路径
        validate_path_component(output_dir)
        
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 方法1: 使用参数数组调用 rpm2cpio
        # 注意：rpm2cpio 不支持 -D 参数，需要先解压到临时目录再移动
        import tempfile
        import shutil
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 第一步：使用 rpm2cpio 解压到临时目录
            # rpm2cpio 输出到 stdout，通过 cpio 解压
            # 使用参数数组形式调用
            try:
                # 执行 rpm2cpio 获取 cpio 数据
                rpm2cpio_cmd = ['rpm2cpio', str(rpm_path_obj)]
                rpm2cpio_result = subprocess.run(
                    rpm2cpio_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                    text=False  # 保持二进制模式
                )
                
                # 使用 cpio 解压到临时目录（使用参数数组）
                cpio_cmd = ['cpio', '-idm']
                cpio_result = subprocess.run(
                    cpio_cmd,
                    input=rpm2cpio_result.stdout,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(temp_path),  # 在临时目录中执行
                    check=False  # 我们手动检查返回值
                )
                
                if cpio_result.returncode != 0:
                    return f"解压RPM包失败: cpio错误 - {cpio_result.stderr.decode('utf-8', errors='ignore')}"
                
                # 安全地移动文件到目标目录
                for item in temp_path.iterdir():
                    dest = output_path / item.name
                    # 检查目标路径是否在输出目录内
                    try:
                        dest.resolve().relative_to(output_path)
                    except ValueError:
                        return f"安全检查失败: 文件 {item.name} 可能逃逸目标目录"
                    
                    if item.is_file():
                        shutil.move(str(item), str(dest))
                    elif item.is_dir():
                        # 如果目录已存在，合并内容
                        if dest.exists():
                            shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                            shutil.rmtree(str(item))
                        else:
                            shutil.move(str(item), str(dest))
                
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                return f"解压RPM包失败: {error_msg}"
        
        # 替代方法：如果系统支持 rpm2cpio 的 -D 参数，也可以使用
        # 但为了兼容性，我们使用上面的方法
        
        return f"成功解压RPM包到: {output_dir}"
    except ValueError as e:
        return f"安全检查失败: {str(e)}"
    except Exception as e:
        return f"解压RPM包失败: {str(e)}"

@mcp.tool()
def rpm_unpack_alt(rpm_path: str, output_dir: str) -> str:
    """解压RPM包到指定目录（备选方案）
    
    使用更简洁的方式，但需要系统支持 rpm2cpio 的管道操作。
    该版本更高效但可能在某些系统上不兼容。
    
    Args:
        rpm_path: RPM文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        # 验证并规范化路径
        rpm_path_obj = Path(rpm_path).resolve()
        if not rpm_path_obj.exists():
            return f"错误: RPM文件不存在: {rpm_path}"
        
        # 验证输出目录路径
        validate_path_component(output_dir)
        
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 使用管道但不使用shell
        # 创建两个进程，一个读取，一个写入
        import subprocess
        import tempfile
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 启动 rpm2cpio 进程
            rpm2cpio_proc = subprocess.Popen(
                ['rpm2cpio', str(rpm_path_obj)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # 启动 cpio 进程，从 stdin 读取
            cpio_proc = subprocess.Popen(
                ['cpio', '-idm'],
                stdin=rpm2cpio_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(temp_path)
            )
            
            # 关闭 rpm2cpio 的 stdout，让 cpio 可以正常读取
            rpm2cpio_proc.stdout.close()
            
            # 等待进程完成
            rpm2cpio_return = rpm2cpio_proc.wait()
            cpio_stdout, cpio_stderr = cpio_proc.communicate()
            cpio_return = cpio_proc.returncode
            
            if rpm2cpio_return != 0 or cpio_return != 0:
                error_msg = cpio_stderr.decode('utf-8', errors='ignore') if cpio_stderr else "未知错误"
                return f"解压RPM包失败: {error_msg}"
            
            # 安全地移动文件（使用shutil）
            import shutil
            for item in temp_path.iterdir():
                dest = output_path / item.name
                # 安全检查
                try:
                    dest.resolve().relative_to(output_path)
                except ValueError:
                    return f"安全检查失败: 文件 {item.name} 可能逃逸目标目录"
                
                if item.is_file():
                    shutil.move(str(item), str(dest))
                elif item.is_dir():
                    if dest.exists():
                        shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                        shutil.rmtree(str(item))
                    else:
                        shutil.move(str(item), str(dest))
        
        return f"成功解压RPM包到: {output_dir}"
    except ValueError as e:
        return f"安全检查失败: {str(e)}"
    except Exception as e:
        return f"解压RPM包失败: {str(e)}"

@mcp.tool()
def list_tar_contents(tar_path: str) -> str:
    """列出tar压缩包的内容（安全预览）
    
    Args:
        tar_path: tar文件路径
        
    Returns:
        压缩包内容列表
    """
    try:
        tar_path_obj = Path(tar_path).resolve()
        if not tar_path_obj.exists():
            return f"错误: 压缩包不存在: {tar_path}"
        
        with tarfile.open(tar_path) as tar:
            members = tar.getmembers()
            
            # 安全检查：预览时也检测危险成员
            dangerous = []
            safe_members = []
            
            for member in members:
                if member.name.startswith('/') or '..' in member.name.split(os.sep):
                    dangerous.append(f"⚠️ 路径遍历: {member.name}")
                elif member.issym() or member.islnk() or member.isdev():
                    dangerous.append(f"⚠️ 危险类型: {member.name} (类型: {member.type})")
                else:
                    size = member.size if member.isfile() else 0
                    safe_members.append(f"{member.name} ({size} bytes)")
            
            result = []
            if safe_members:
                result.append("安全内容:")
                result.extend(safe_members)
            if dangerous:
                result.append("\n⚠️ 警告: 检测到危险内容:")
                result.extend(dangerous)
                result.append("这些内容将被阻止解压")
            
            return "\n".join(result) if result else "压缩包为空"
    except Exception as e:
        return f"读取压缩包失败: {str(e)}"

if __name__ == "__main__":
    mcp.run()