import re
import shutil
import subprocess

import ast_parser
from ast_parser import ASTParser
from common import Language


def remove_comments(string):
    pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
    # first group captures quoted strings (double or single)
    # second group captures comments (//single-line or /* multi-line */)
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    def _replacer(match):
        # if the 2nd group (capturing comments) is not None,
        # it means we have captured a non-quoted (real) comment string.
        if match.group(2) is not None:
            return ""  # so we will return empty to remove the comment
        else:  # otherwise, we will return the 1st group
            return match.group(1)  # captured quoted-string
    return regex.sub(_replacer, string)


def del_comment(src):
    with open(src, "r", errors="ignore") as f:
        file_contents = f.read()
    c_regex = re.compile(
        r'(?P<comment>//.*?$)|(?P<multilinecomment>/\*.*?\*/)|(?P<noncomment>\'(\\.|[^\\\'])*\'|"(\\.|[^\\"])*"|.[^/\'"]*)',
        re.DOTALL | re.MULTILINE,
    )
    file_contents = "".join(
        [
            c.group("noncomment")
            for c in c_regex.finditer(file_contents)
            if c.group("noncomment")
        ]
    )
    with open(src, "w") as f:
        f.write(file_contents)


def get_comment(code):
    c_regex = re.compile(
        r'(?P<comment>//.*?$)|(?P<multilinecomment>/\*.*?\*/)|(?P<noncomment>\'(\\.|[^\\\'])*\'|"(\\.|[^\\"])*"|.[^/\'"]*)',
        re.DOTALL | re.MULTILINE,
    )
    comment = [
        c.group("comment")
        for c in c_regex.finditer(code)
        if c.group("comment")
    ]
    multilinecomment = [
        c.group("multilinecomment")
        for c in c_regex.finditer(code)
        if c.group("multilinecomment")
    ]
    all_comment = set()
    for comma in comment:
        all_comment.add(comma)
    for comma in multilinecomment:
        all_comment.add(comma)
    return all_comment


def remove_linebreaks(string):
    return re.sub(r"\n", "", string)


def remove_spaces(string):
    return re.sub(r"\s+", "", string)


def remove_empty_lines(string) -> str:
    return re.sub(r"^\s*$\n", "", string, flags=re.MULTILINE)


def remove_param_linebreaks(string) -> str:
    return re.sub(r",\s*", ", ", string)


def normalize(code: str, del_comments: bool = True) -> str:
    if del_comments:
        code = remove_comments(code)
    code = remove_linebreaks(code)
    code = remove_spaces(code)
    return code.strip()


def add_bracket_c(code: str, language: Language):
    code_bytes = code.encode()
    parser = ASTParser(code, language)
    nodes = parser.query_all(ast_parser.TS_COND_STAT)
    need_modified_bytes = []
    for node in nodes:
        consequence_node = node.child_by_field_name("consequence")
        if consequence_node is None:
            continue
        if consequence_node.type != "compound_statement":
            if (consequence_node.start_byte, consequence_node.end_byte) not in need_modified_bytes:
                need_modified_bytes.append((consequence_node.start_byte, consequence_node.end_byte))
        alternative_node = node.child_by_field_name("alternative")
        if alternative_node is None:
            continue
        alternative_node = alternative_node.named_child(0)
        if alternative_node is not None and alternative_node.type != "compound_statement" and alternative_node.type != "if_statement":
            # print(code_bytes[alternative_node.start_byte:alternative_node.end_byte+1])
            if (alternative_node.start_byte, alternative_node.end_byte) not in need_modified_bytes:
                st = alternative_node.start_byte
                ed = alternative_node.end_byte
                need_modified_bytes.append((alternative_node.start_byte, alternative_node.end_byte))
    need_modified_bytes = sorted(need_modified_bytes)
    i = 0
    while i < len(need_modified_bytes):
        st, ed = need_modified_bytes[i]
        if ed - st <= 1:
            i += 1
            continue
        code_bytes = code_bytes[:st] + b"{\n" + code_bytes[st:ed + 1] + b"}\n" + code_bytes[ed + 1:]
        j = i + 1
        while j < len(need_modified_bytes):
            st_next, ed_next = need_modified_bytes[j]
            if st_next >= st and st_next <= ed:
                st_next += 2
            else:
                st_next += 4
            if ed_next >= st and ed_next <= ed:
                ed_next += 2
            else:
                ed_next += 4
            need_modified_bytes[j] = (st_next, ed_next)
            j += 1
        i += 1
    return code_bytes.decode()


def del_lineBreak_Java(code: str):
    lines = code.split("\n")
    lines = [line + "\n" for line in lines]
    i = 0
    relines = ""
    while i < len(lines):
        line = lines[i]
        i += 1

        while (
            not (
                line.replace(" ", "").rstrip().endswith(";")
                and line.lstrip().startswith("for ")
                and line.count(";") == 3
            )
            and not (
                line.replace(" ", "").rstrip().endswith(";")
                and not (
                    line.lstrip().startswith("try") or line.lstrip().startswith("for ")
                )
            )
            and not line.replace(" ", "").rstrip().endswith("}")
            and not (
                (
                    line.lstrip().startswith("if ")
                    or line.lstrip().startswith("for ")
                    or line.lstrip().startswith("while ")
                    or line.lstrip().startswith("switch ")
                    or line.lstrip().startswith("else if")
                )
                and line.replace(" ", "").rstrip().endswith(")")
            )
            and not (
                line.strip().startswith("else")
                and not line.lstrip().startswith("else if")
            )
            and not line.replace(" ", "").rstrip().endswith("{")
            and not (
                line.replace(" ", "").lstrip().startswith("@")
                and line.replace(" ", "").rstrip().endswith(")")
            )
            and not (line.strip().startswith("case") and line.rstrip().endswith(":"))
            and not line.replace(" ", "") == "\n"
            and i < len(lines)
        ):
            if line.replace(" ", "").lstrip().startswith("@"):
                tmp_lines = line.strip().split(" ")
                if len(tmp_lines) == 1:
                    break
            line = line[0:-1] + " "
            line += lines[i].lstrip()
            i += 1

        # 防止x=(int)换行y这种情况产生
        if (
            line.replace(" ", "").rstrip().endswith(")")
            and "=" in line
            and not (
                line.lstrip().startswith("if ")
                or line.lstrip().startswith("for ")
                or line.lstrip().startswith("else if ")
                or line.lstrip().startswith("@")
            )
        ):
            line = line[0:-1] + " "
            line += lines[i].lstrip()
            i += 1

        while line.lstrip().startswith("for ") and not (
            line.replace(" ", "").rstrip().endswith(")")
            or line.replace(" ", "").rstrip().endswith("{")
            or line.replace(" ", "").rstrip().endswith(";")
        ):
            line = line[0:-1] + " "
            line += lines[i].lstrip()
            i += 1

        while (
            line.replace(" ", "").lstrip().startswith("@")
            and not line.replace(" ", "").lstrip().startswith("@Override")
            and not line.replace(" ", "").lstrip().startswith("@Deprecated")
            and (
                (line.replace(" ", "").rstrip().endswith(","))
                or (
                    line.replace(" ", "").rstrip().endswith("(")
                    or (line.replace(" ", "").rstrip().endswith("{"))
                )
            )
        ):
            line = line[0:-1] + " "
            line += lines[i].lstrip()
            i += 1

        if line.replace(" ", "").lstrip().startswith("@") and (
            lines[i].replace(" ", "").rstrip().startswith(")")
            or lines[i].replace(" ", "").rstrip().startswith("}")
        ):
            line = line[0:-1] + " "
            line += lines[i].lstrip()
            i += 1

        # 判断初始化数组语句的大括号
        temp_lines = line.split(" ")
        if (
            "new" in temp_lines
            and line.replace(" ", "").rstrip().endswith("{")
            and not line.lstrip().startswith("try ")
            and not lines[i].replace(" ", "").lstrip().startswith("@")
            and "->" not in temp_lines
        ) or (
            "String[]" in temp_lines
            and line.replace(" ", "").rstrip().endswith("{")
            and "public" not in temp_lines
            and "private" not in temp_lines
            and "protected" not in temp_lines
        ):
            line = line[0:-1] + " "
            line += lines[i]
            i += 1
            while (
                not line.replace(" ", "").rstrip().endswith(";")
                and not line.replace(" ", "").rstrip().endswith("}")
                and not line.replace(" ", "").rstrip().endswith(")")
                and not line.replace(" ", "").rstrip().endswith("{")
                and not line.replace(" ", "").lstrip().startswith("@")
                and not line.replace(" ", "").lstrip().startswith("else")
                and i < len(lines)
            ):
                if (
                    lines[i].strip().startswith("public")
                    or lines[i].strip().startswith("private")
                    or lines[i].strip().startswith("protected")
                    or lines[i].strip().startswith("@")
                ):
                    line += "\n"
                    break
                line = line[0:-1] + " "
                line += lines[i].lstrip()
                i += 1

            while not line.rstrip().endswith(";"):
                if (
                    lines[i].strip().startswith("public")
                    or lines[i].strip().startswith("private")
                    or lines[i].strip().startswith("protected")
                    or lines[i].strip().startswith("@")
                ):
                    line += "\n"
                    break
                line = line[0:-1] + " "
                line += lines[i].lstrip()
                i += 1

        if line.replace(" ", "").rstrip().endswith("});") and "{" not in line:
            k = line.rfind("}")
            line = line[: k + 1] + "\n" + line[k + 1:]
        elif line.replace(" ", "").lstrip().startswith("}));"):
            k = line.rfind("}")
            line = line[: k + 1] + "\n" + line[k + 1:]

        if (
            line.lstrip().startswith("if ")
            or line.lstrip().startswith("for ")
            or line.lstrip().startswith("while ")
            or line.lstrip().startswith("try ")
            or line.lstrip().startswith("catch ")
            or line.lstrip().startswith("else if")
            or line.lstrip().startswith("switch ")
        ):
            string_literals = re.findall(r'"(?:\\.|[^\\"])*"', line)
            tmp = line
            for j, literal in enumerate(string_literals):
                placeholder = f"__string_literal_{j}__"
                tmp = tmp.replace(literal, placeholder)
            while tmp.count("(") != tmp.count(")") or not (
                tmp.rstrip().endswith("{")
                or tmp.rstrip().endswith(")")
                or tmp.rstrip().endswith(";")
                or tmp.rstrip().endswith("}")
            ):
                tmp = tmp[0:-1] + " "
                tmp += lines[i].lstrip()
                i += 1
            for j, literal in enumerate(string_literals):
                placeholder = f"__string_literal_{j}__"
                tmp = tmp.replace(placeholder, literal)
            line = tmp

        # print(line)
        if line.replace(" ", "").lstrip().startswith("."):
            relines = relines[0:-1] + line.lstrip()
        elif line.replace(" ", "").lstrip().startswith("{"):
            relines = relines[0:-1] + line.lstrip()
        elif (
            line.lstrip().startswith("throws")
            or line.replace(" ", "").lstrip().startswith("||")
            or line.replace(" ", "").lstrip().startswith("&&")
            or line.replace(" ", "").lstrip().startswith("+")
            or line.replace(" ", "").lstrip().startswith("-")
            or line.replace(" ", "").lstrip().startswith("*")
            or line.replace(" ", "").lstrip().startswith(")")
            or line.replace(" ", "").lstrip().startswith(">")
            or line.replace(" ", "").lstrip().startswith("<")
            or line.replace(" ", "").lstrip().startswith(":")
            or line.replace(" ", "").lstrip().startswith("==")
            or line.replace(" ", "").lstrip().startswith("?")
            or line.replace(" ", "").lstrip().startswith("!=")
        ):
            relines = relines[0:-1] + " " + line.lstrip()
        elif line.replace(" ", "").lstrip().startswith("},"):
            relines = relines + line
        elif (
            line.replace(" ", "").lstrip().startswith("}")
            and not line.replace(" ", "").rstrip().endswith("};")
            and not (
                line.replace(" ", "").lstrip().startswith("})")
                and not line.replace(" ", "").lstrip().startswith("}){")
            )
        ):
            j = line.find("}")
            relines = relines + line[0: j + 1] + "\n" + line[0:j] + line[j + 1:]
        elif line.replace(" ", "").lstrip().startswith("})."):
            k = line.rfind("}")
            relines = relines + line[: k + 1] + "\n" + line[k + 1:]
        elif line.replace(" ", "").lstrip().startswith(
            "@Override"
        ) and not line.replace(" ", "").rstrip().endswith("@Override") and not line.replace(" ", "").rstrip().startswith("@OverrideMustInvoke"):
            k = line.find("@Override")
            relines = (
                relines
                + line[: k + len("@Override")]
                + "\n"
                + line[k + len("@Override"):]
            )
        elif line.replace(" ", "").lstrip().startswith(
            "@Deprecated"
        ) and not line.replace(" ", "").rstrip().endswith("@Deprecated"):
            k = line.find("@Deprecated")
            relines = (
                relines
                + line[: k + len("@Deprecated")]
                + "\n"
                + line[k + len("@Deprecated"):]
            )
        elif line.replace(" ", "") != "\n":
            relines += line
    return relines


def del_lineBreak_C(code):
    comments = get_comment(code)
    comment_map = {}
    cnt = 0
    for comment in comments:
        repl = f"__COMMENT__{cnt};"
        code = code.replace(comment, repl)
        comment_map[repl] = comment
        cnt += 1
    lines = code.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].endswith("\\"):
            temp = i
            while lines[i].endswith("\\"):
                i += 1
            lines[temp] = lines[temp][:-2]
            for k in range(temp + 1, i + 1):
                if k == len(lines):
                    break
                lines[temp] += " "
                lines[temp] += lines[k][:-2].strip()
                lines[k] = "\n"
        else:
            i += 1
    i = 0
    while i < len(lines):
        if (
            lines[i].strip() == ""
            or lines[i].strip().startswith("#")
        ):
            i += 1
        else:
            temp = i
            while (
                i < len(lines)
                and not lines[i].strip().endswith(";")
                and not lines[i].strip().endswith("{")
                and not lines[i].strip().endswith(")")
                and not lines[i].strip().endswith("}")
                and not lines[i].strip().endswith(":")
                and not lines[i].strip().startswith("#")
            ):
                i += 1
            if i < len(lines) and lines[i].strip().startswith("#"):
                i -= 1
            if temp != i:
                lines[temp] = lines[temp]
            for j in range(temp + 1, i + 1):
                if j == len(lines):
                    break
                lines[temp] += " "
                lines[temp] += lines[j].strip()
                lines[j] = ""
            if temp == i:
                i += 1
    code = "\n".join(lines)
    for repl in comment_map.keys():
        code = code.replace(repl, comment_map[repl])
    return code


def del_macros(code):
    lines = code.split("\n")
    # Single-word macros: MUST use \b word boundaries to avoid corrupting
    # identifiers that contain the macro as a substring (e.g. "IN" would
    # destroy EINVAL→EVAL, EINPROGRESS→EPROGRESS; "OUT" would destroy
    # TIMEOUT, OUTPUT, etc.).
    _single_word_macros = [
        "INLINE", "TRIO_PRIVATE_STRING", "GF_EXPORT", "LOCAL",
        "IN", "OUT", "_U_", "EFIAPI", "UNUSED_PARAM",
        "__rte_always_inline", "__init", "__user", "UNUSED",
    ]
    # Multi-word strings that need literal replacement.
    _multi_word_replacements = [
        '__declspec(dllexport) mrb_value',
        'extern "C"',
        "METHODDEF(void)", "METHODDEF(JDIMENSION)",
    ]
    # Pre-compile regex patterns so they are only built once.
    _single_word_patterns = [
        re.compile(r'\b' + re.escape(m) + r'\b') for m in _single_word_macros
    ]

    i = 0
    while i < len(lines):
        if lines[i].endswith("\\"):
            temp = i
            while lines[i].endswith("\\"):
                i += 1
            lines[temp] = lines[temp][:-2]
            for k in range(temp + 1, i + 1):
                if k == len(lines):
                    break
                lines[temp] += " "
                lines[temp] += lines[k][:-2].strip()
                lines[k] = "\n"
        else:
            i += 1

    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("#") and not lines[i].strip().startswith("#include"):
            lines[i] = ""
        for pattern in _single_word_patterns:
            lines[i] = pattern.sub('', lines[i])
        for replacement in _multi_word_replacements:
            lines[i] = lines[i].replace(replacement, "")
        i += 1
    return "\n".join(lines)


def _run_astyle_or_fallback(code: str) -> str:
    if shutil.which("astyle") is None:
        return code.strip()
    try:
        return subprocess.run(
            [
                "astyle",
                "--style=java",
                "--keep-one-line-statements",
                "--max-code-length=200",
                "--delete-empty-lines",
            ],
            input=code.encode(),
            stdout=subprocess.PIPE,
            check=False,
        ).stdout.decode().strip()
    except FileNotFoundError:
        return code.strip()


def format(code: str, language: Language, del_comment: bool, del_linebreak: bool, add_bracket: bool = True, del_macro: bool = True) -> str:
    code = _run_astyle_or_fallback(code)
    if del_comment:
        code = remove_comments(code)
    if del_macro and language == Language.C:
        code = del_macros(code)
    if del_linebreak:
        if language == Language.JAVA:
            code = del_lineBreak_Java(code)
        elif language == Language.C:
            code = del_lineBreak_C(code)
    if add_bracket:
        if language == Language.C:
            code = add_bracket_c(code, language)
    code = remove_empty_lines(code)
    code = _run_astyle_or_fallback(code)
    return code


def format_file(file_path: str, language: Language, del_linebreak: bool) -> str:
    with open(file_path, 'r') as file:
        code = file.read()
    code = format(code, language, del_linebreak=del_linebreak, del_comment=True)
    return code

def format_and_del_comment_c_cpp(code: str) -> str:
    """
    格式化C/C++代码并删除注释
    """
    # 删除注释
    code = remove_comments(code)
    
    # 删除宏定义
    code = del_macros(code)
    
    # 删除换行符
    code = del_lineBreak_C(code)
    
    # 添加括号
    code = add_bracket_c(code, Language.C)
    
    # 删除空行
    code = remove_empty_lines(code)
    
    return code

if __name__ == "__main__":
    code = """
static int do_last(struct nameidata *nd, struct file *file, const struct open_flags *op) {
    struct dentry *dir = nd->path.dentry;
    kuid_t dir_uid = dir->d_inode->i_uid;
    umode_t dir_mode = dir->d_inode->i_mode;
    int open_flag = op->open_flag;
    /* PLACEHOLDER: DO NOT DELETE THIS COMMENT */
    if (nd->last_type !=
        LAST_NORM) {
        error = handle_dots(nd, nd->last_type);//xxxxx
    /* PLACEHOLDER: DO NOT DELETE THIS COMMENT */
    }
}
    """
    code = format(code, Language.C, del_linebreak=True, del_comment=True)
    print(code)
