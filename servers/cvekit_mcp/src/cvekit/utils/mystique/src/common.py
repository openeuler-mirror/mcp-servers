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
