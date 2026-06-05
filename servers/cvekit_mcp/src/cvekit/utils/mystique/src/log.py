import logging
import os
import re
from datetime import datetime


_DATE_TIME_LOG_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.log$")


def _build_runtime_log_path(log_file_path: str) -> str:
    log_dir = os.path.dirname(log_file_path) or "."
    log_filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}.log"
    return os.path.join(log_dir, log_filename)


def _cleanup_old_logs(log_dir: str, keep_count: int = 30):
    candidates = [
        os.path.join(log_dir, filename)
        for filename in os.listdir(log_dir)
        if _DATE_TIME_LOG_PATTERN.match(filename)
    ]
    candidates.sort()
    if len(candidates) <= keep_count:
        return
    for old_file in candidates[: len(candidates) - keep_count]:
        try:
            os.remove(old_file)
        except OSError:
            pass


def init_logger(logger: logging.Logger, log_level: int, log_file_path: str | None = None):
    logger.setLevel(logging.DEBUG)

    shell_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%H:%M:%S"
    )
    ch = logging.StreamHandler()
    ch.set_name("shell")
    ch.setLevel(log_level)
    ch.setFormatter(shell_formatter)
    logger.addHandler(ch)

    if log_file_path is None:
        return

    file_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    runtime_log_path = _build_runtime_log_path(log_file_path)
    log_dir = os.path.dirname(runtime_log_path) or "."
    os.makedirs(log_dir, exist_ok=True)
    _cleanup_old_logs(log_dir, keep_count=30)
    fh = logging.FileHandler(runtime_log_path, encoding="utf-8")
    fh.set_name("file")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)


def set_logger_prefix(logger: logging.Logger, prefix: str = ""):
    default_file_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    default_shell_formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s]: %(message)s", datefmt="%H:%M:%S"
    )
    file_formatter = logging.Formatter(
        f"[%(asctime)s][%(levelname)s][{prefix}]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    shell_formatter = logging.Formatter(
        f"[%(asctime)s][%(levelname)s][{prefix}]: %(message)s", datefmt="%H:%M:%S"
    )
    if prefix == "":
        file_formatter = default_file_formatter
        shell_formatter = default_shell_formatter
    for handler in logger.handlers:
        if handler.name == "file":
            handler.setFormatter(file_formatter)
        elif handler.name == "shell":
            handler.setFormatter(shell_formatter)
