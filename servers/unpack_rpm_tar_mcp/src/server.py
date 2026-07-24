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
        source = Path(source_path)
        if not source.exists():
            return f"错误: 源路径不存在: {source_path}"
        
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
    
    Args:
        tar_path: 要解压的tar.gz文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        tar_path_obj = Path(tar_path)
        if not tar_path_obj.exists():
            return f"错误: 压缩包不存在: {tar_path}"
        
        output_path = Path(output_dir)
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
    
    注意：RPM包解压本身不涉及tar路径遍历问题，
    但仍需确保输出目录安全。
    
    Args:
        rpm_path: RPM文件路径
        output_dir: 解压目标目录
        
    Returns:
        操作结果信息
    """
    try:
        rpm_path_obj = Path(rpm_path)
        if not rpm_path_obj.exists():
            return f"错误: RPM文件不存在: {rpm_path}"
        
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 使用subprocess执行解压
        # 注意：cpio -D 选项可以指定解压目录，防止路径遍历
        cmd = f"rpm2cpio {rpm_path} | cpio -idm -D {output_path}"
        
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        
        return f"成功解压RPM包到: {output_dir}"
    except subprocess.CalledProcessError as e:
        return f"解压RPM包失败: {e.stderr if e.stderr else str(e)}"
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
        tar_path_obj = Path(tar_path)
        if not tar_path_obj.exists():
            return f"错误: 压缩包不存在: {tar_path}"
        
        with tarfile.open(tar_path) as tar:
            members = tar.getmembers()
            
            # 安全检查：预览时也检测危险成员
            dangerous = []
            safe_members = []
            
            for member in members:
                if member.name.startswith('/') or '..' in member.name.split(os.sep):
                    dangerous.append(f"{member.name}")
                elif member.issym() or member.islnk() or member.isdev():
                    dangerous.append(f"{member.name} : {member.type})")
                else:
                    size = member.size if member.isfile() else 0
                    safe_members.append(f"{member.name} ({size} bytes)")
            
            result = []
            if safe_members:
                result.append("安全内容:")
                result.extend(safe_members)
            if dangerous:
                result.append("警告: 检测到危险内容:")
                result.extend(dangerous)
                result.append("这些内容将被阻止解压")
            
            return "\n".join(result) if result else "压缩包为空"
    except Exception as e:
        return f"读取压缩包失败: {str(e)}"

if __name__ == "__main__":
    mcp.run()