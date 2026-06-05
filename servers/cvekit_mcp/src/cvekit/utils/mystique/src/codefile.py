import os

import format
from common import Language


class CodeFile:
    def __init__(self, file_path: str, code: str):
        self.file_path = file_path
        self.code = code
        self.language = Language.JAVA if file_path.endswith(".java") else Language.C

    @property
    def formated_code(self):
        return format.format(self.code, self.language, del_comment=False, del_linebreak=False, add_bracket=False)

    @property
    def formated_code_for_project(self):
        # Keep original C macros (e.g. __user) in project AST/method code so
        # they are not lost in final migrated output.
        return format.format(
            self.code,
            self.language,
            del_comment=False,
            del_linebreak=False,
            add_bracket=False,
            del_macro=False,
        )


def create_code_tree(code_files: list[CodeFile], dir: str, overwrite: bool = False) -> str:
    code_dir = os.path.join(dir, "code")
    if os.path.exists(code_dir) and not overwrite:
        return code_dir
    os.makedirs(code_dir, exist_ok=True)

    for file in code_files:
        # Joern needs formatted code with macros removed to parse CPG/PDG correctly.
        code = file.formated_code
        path = file.file_path
        assert path is not None
        os.makedirs(os.path.dirname(os.path.join(code_dir, path)), exist_ok=True)
        with open(os.path.join(code_dir, path), "w") as f:
            f.write(code)
    return code_dir
