import os
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from mcp.server.fastmcp import FastMCP

BACKUP_DIR = "/var/backups/mcp"  # 备份存储目录
MAX_BACKUPS = 10                  # 最多保留几个备份
COMPRESSION = True                # 是否压缩（True=tar.gz，False=tar）

ALLOWED_BACKUP_DIRS = ["/home", "/opt", "/var/www", "/data"]  # 允许备份的目录白名单
ALLOWED_RESTORE_DIRS = ["/home", "/opt", "/tmp", "/data"]     # 允许恢复的目录白名单
MAX_PATH_LENGTH = 4096             # 最大路径长度
ENABLE_AUDIT_LOG = True           # 是否启用审计日志

audit_logger = None


def _initialize_directories():
    """
    初始化必要的目录
    在MCP服务器启动时自动创建备份目录和日志目录
    """
    global audit_logger, ENABLE_AUDIT_LOG
    
    directories_to_create = [
        (BACKUP_DIR, "备份目录"),
        (os.path.dirname('/var/log/mcp/backup_manager.log'), "日志目录")
    ]
    
    for directory, description in directories_to_create:
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as e:
            print(f"创建{description}失败: {directory}")
            print(f"错误: {str(e)}")
    
    # 配置审计日志
    if ENABLE_AUDIT_LOG:
        try:
            logging.basicConfig(
                filename='/var/log/mcp/backup_manager.log',
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s'
            )
            audit_logger = logging.getLogger('backup_manager_audit')
            print(f"✓ 审计日志已启用: /var/log/mcp/backup_manager.log")
        except Exception as e:
            print(f"✗ 审计日志配置失败: {str(e)}")
            print(f"  审计日志将被禁用")
            audit_logger = None


def _log_audit(action: str, user: str, details: dict, status: str = "success"):
    """记录审计日志"""
    if audit_logger:
        audit_logger.info(f"Action={action}, User={user}, Status={status}, Details={details}")


def _validate_path(path: str, allowed_dirs: list, operation: str) -> tuple[bool, str]:
    """
    验证路径是否安全
    
    Args:
        path: 要验证的路径
        allowed_dirs: 允许的目录白名单
        operation: 操作类型（backup/restore）
    
    Returns:
        (is_valid, error_message)
    """
    if len(path) > MAX_PATH_LENGTH:
        return False, f"路径长度超过限制（{MAX_PATH_LENGTH}字符）"
    
    if not path or not path.strip():
        return False, "路径不能为空"
    
    try:
        normalized_path = os.path.realpath(os.path.abspath(path))
    except Exception as e:
        return False, f"路径解析失败: {str(e)}"
    
    dangerous_patterns = ["../", "..\\", "~", "$(", "`", ";", "&", "|", ">"]
    for pattern in dangerous_patterns:
        if pattern in path:
            return False, f"路径包含非法字符: {pattern}"
    
    is_allowed = False
    for allowed_dir in allowed_dirs:
        try:
            allowed_real = os.path.realpath(os.path.abspath(allowed_dir))
            if normalized_path.startswith(allowed_real):
                is_allowed = True
                break
        except Exception:
            continue
    
    if not is_allowed:
        return False, f"路径不在允许的目录白名单中。允许的目录: {', '.join(allowed_dirs)}"
    
    if operation == "backup" and not os.path.exists(normalized_path):
        return False, f"路径不存在: {path}"
    
    return True, normalized_path


def _validate_backup_file(backup_file: str) -> tuple[bool, str]:
    """
    验证备份文件路径是否安全
    
    Args:
        backup_file: 备份文件路径
    
    Returns:
        (is_valid, error_message_or_normalized_path)
    """
    if len(backup_file) > MAX_PATH_LENGTH:
        return False, f"路径长度超过限制（{MAX_PATH_LENGTH}字符）"
    
    if not backup_file or not backup_file.strip():
        return False, "路径不能为空"
    
    try:
        normalized_path = os.path.realpath(os.path.abspath(backup_file))
    except Exception as e:
        return False, f"路径解析失败: {str(e)}"
    
    dangerous_patterns = ["../", "..\\", "~", "$(", "`", ";", "&", "|", ">"]
    for pattern in dangerous_patterns:
        if pattern in backup_file:
            return False, f"路径包含非法字符: {pattern}"
    
    try:
        backup_dir_real = os.path.realpath(os.path.abspath(BACKUP_DIR))
        if not normalized_path.startswith(backup_dir_real):
            return False, f"备份文件必须在备份目录中: {BACKUP_DIR}"
    except Exception as e:
        return False, f"备份目录解析失败: {str(e)}"
    
    if not os.path.exists(normalized_path):
        return False, f"备份文件不存在: {backup_file}"
    
    if not os.path.isfile(normalized_path):
        return False, f"路径不是文件: {backup_file}"
    
    if COMPRESSION:
        if not normalized_path.endswith('.tar.gz'):
            return False, f"备份文件必须是.tar.gz格式"
    else:
        if not normalized_path.endswith('.tar'):
            return False, f"备份文件必须是.tar格式"
    
    return True, normalized_path


def _cleanup_old_backups():
    """内部函数：自动删除旧备份，保留最新的MAX_BACKUPS个"""
    if not os.path.exists(BACKUP_DIR):
        return
    
    # 获取所有备份文件并按时间排序（最新的在前）
    backups = []
    for fname in os.listdir(BACKUP_DIR):
        path = os.path.join(BACKUP_DIR, fname)
        if os.path.isfile(path):
            backups.append((path, os.path.getmtime(path)))
    
    backups.sort(key=lambda x: x[1], reverse=True)
    
    # 删除多余的旧备份
    for path, _ in backups[MAX_BACKUPS:]:
        try:
            os.remove(path)
        except Exception:
            pass

mcp = FastMCP("简易备份工具")


@mcp.tool()
def create_backup(source_path: str) -> dict:
    """
    创建备份（只需告诉它要备份哪个文件夹/文件即可）
    :param source_path: 要备份的路径，例如 "/home/user/docs"
    """
    # 验证源路径
    is_valid, result = _validate_path(source_path, ALLOWED_BACKUP_DIRS, "backup")
    if not is_valid:
        _log_audit("create_backup", "unknown", {"source_path": source_path}, "failed")
        return {"状态": "失败", "原因": result}
    
    normalized_source = result
    
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
    except Exception as e:
        _log_audit("create_backup", "unknown", {"source_path": source_path, "error": str(e)}, "failed")
        return {"状态": "失败", "原因": f"创建备份目录失败: {str(e)}"}
    
    # 自动生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(normalized_source.rstrip('/'))
    ext = ".tar.gz" if COMPRESSION else ".tar"
    backup_file = os.path.join(BACKUP_DIR, f"{base_name}_{timestamp}{ext}")
    
    try:
        if COMPRESSION:
            cmd = ["tar", "-czf", backup_file, "-C", os.path.dirname(normalized_source), os.path.basename(normalized_source)]
        else:
            cmd = ["tar", "-cf", backup_file, "-C", os.path.dirname(normalized_source), os.path.basename(normalized_source)]
        
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # 清理旧文件
        _cleanup_old_backups()
        
        size_mb = round(os.path.getsize(backup_file) / (1024 * 1024), 2)
        
        # 记录审计日志
        _log_audit("create_backup", "unknown", {
            "source_path": normalized_source,
            "backup_file": backup_file,
            "size_mb": size_mb
        }, "success")
        
        return {
            "状态": "成功",
            "备份文件": backup_file,
            "大小": f"{size_mb} MB"
        }
    except subprocess.CalledProcessError as e:
        _log_audit("create_backup", "unknown", {
            "source_path": normalized_source,
            "error": f"命令执行失败: {e.stderr}"
        }, "failed")
        return {"状态": "失败", "原因": f"备份命令执行失败: {e.stderr}"}
    except Exception as e:
        _log_audit("create_backup", "unknown", {
            "source_path": normalized_source,
            "error": str(e)
        }, "failed")
        return {"状态": "失败", "原因": str(e)}


@mcp.tool()
def restore_backup(backup_file: str, target_path: str) -> dict:
    """
    恢复备份
    :param backup_file: 备份文件路径（从list_backups里复制）
    :param target_path: 恢复到哪个位置
    """
    # 验证备份文件
    is_valid, result = _validate_backup_file(backup_file)
    if not is_valid:
        _log_audit("restore_backup", "unknown", {
            "backup_file": backup_file,
            "target_path": target_path
        }, "failed")
        return {"状态": "失败", "原因": result}
    
    normalized_backup = result
    
    # 验证目标路径
    is_valid, result = _validate_path(target_path, ALLOWED_RESTORE_DIRS, "restore")
    if not is_valid:
        _log_audit("restore_backup", "unknown", {
            "backup_file": backup_file,
            "target_path": target_path
        }, "failed")
        return {"状态": "失败", "原因": result}
    
    normalized_target = result
    
    # 创建目标目录
    try:
        os.makedirs(normalized_target, exist_ok=True)
    except Exception as e:
        _log_audit("restore_backup", "unknown", {
            "backup_file": normalized_backup,
            "target_path": normalized_target,
            "error": str(e)
        }, "failed")
        return {"状态": "失败", "原因": f"创建目标目录失败: {str(e)}"}
    
    try:
        result = subprocess.run(
            ["tar", "-xf", normalized_backup, "-C", normalized_target],
            check=True,
            capture_output=True,
            text=True
        )
        
        # 记录审计日志
        _log_audit("restore_backup", "unknown", {
            "backup_file": normalized_backup,
            "target_path": normalized_target
        }, "success")
        
        return {"状态": "成功", "恢复到": normalized_target}
    except subprocess.CalledProcessError as e:
        _log_audit("restore_backup", "unknown", {
            "backup_file": normalized_backup,
            "target_path": normalized_target,
            "error": f"命令执行失败: {e.stderr}"
        }, "failed")
        return {"状态": "失败", "原因": f"恢复命令执行失败: {e.stderr}"}
    except Exception as e:
        _log_audit("restore_backup", "unknown", {
            "backup_file": normalized_backup,
            "target_path": normalized_target,
            "error": str(e)
        }, "failed")
        return {"状态": "失败", "原因": str(e)}


@mcp.tool()
def list_backups() -> dict:
    """查看所有备份文件，最新的在最上面"""
    try:
        if not os.path.exists(BACKUP_DIR):
            _log_audit("list_backups", "unknown", {"info": "备份目录不存在"}, "success")
            return {"状态": "提示", "信息": "还没有备份文件"}
        
        backups = []
        for fname in os.listdir(BACKUP_DIR):
            path = os.path.join(BACKUP_DIR, fname)
            if os.path.isfile(path):
                stat = os.stat(path)
                backups.append({
                    "文件名": fname,
                    "完整路径": path,
                    "大小": f"{round(stat.st_size / (1024 * 1024), 2)} MB",
                    "创建时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
        
        # 按时间倒序排列
        backups.sort(key=lambda x: x["创建时间"], reverse=True)
        
        # 记录审计日志
        _log_audit("list_backups", "unknown", {
            "backup_count": len(backups),
            "backup_dir": BACKUP_DIR
        }, "success")
        
        return {"状态": "成功", "备份列表": backups}
    except Exception as e:
        _log_audit("list_backups", "unknown", {"error": str(e)}, "failed")
        return {"状态": "失败", "原因": str(e)}


if __name__ == "__main__":
    _initialize_directories()
    mcp.run()