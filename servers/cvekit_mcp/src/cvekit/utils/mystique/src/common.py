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


from enum import Enum


class Mode(Enum):
    CVE = "cve"
    PATCH = "patch"


class Language(Enum):
    JAVA = "javasrc"
    C = "newc"


class HunkType(Enum):
    ADD = "add"
    DEL = "del"
    MOD = "mod"


class ErrorCode(Enum):
    SUCCESS = "SUCCESS"
    EXCEPTION = "EXCEPTION"
    AST_ERROR = "AST_ERROR"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"
    PDG_NOT_FOUND = "PDG_NOT_FOUND"
    SLICE_FAILED = "SLICE_FAILED"
    GROUNDTRUTH_SLICE_FAILED = "GROUNDTRUTH_FAILED"
