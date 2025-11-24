"""
This file is based on the project "patch-backporting":
  https://github.com/OS3Lab/patch-backporting
The original code is licensed under the MIT License.
See third_party/patch-backporting/LICENSE for the full license text.

本文件在 OS3Lab/patch-backporting 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.
"""

import logging

from rich.logging import RichHandler

logger = logging.getLogger("backport")
logger.addHandler(RichHandler())


def add_file_handler(logger: logging.Logger, filename: str):
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler = logging.FileHandler(filename)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
