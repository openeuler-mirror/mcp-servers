"""Tests for mystique func_parser module — regex C function detection."""
import pytest
from func_parser import FuncInfo, parse_functions


class TestFuncInfo:
    def test_dataclass_fields(self):
        fi = FuncInfo(name="foo", start_line=10, end_line=25)
        assert fi.name == "foo"
        assert fi.start_line == 10
        assert fi.end_line == 25

    def test_equality(self):
        a = FuncInfo("foo", 1, 10)
        b = FuncInfo("foo", 1, 10)
        assert a == b

    def test_inequality(self):
        a = FuncInfo("foo", 1, 10)
        b = FuncInfo("bar", 1, 10)
        assert a != b


# ── parse_functions ───────────────────────────────────────────────────

SIMPLE_FUNC = """\
#include <stdio.h>

int add(int a, int b) {
    return a + b;
}
"""

TWO_FUNCS = """\
static int first(void) {
    return 1;
}

void second(int x) {
    printf("%d\\n", x);
}
"""

MULTILINE_SIG = """\
static struct foo *
my_function(struct bar *b, int flags)
{
    return NULL;
}
"""

NO_FUNC = """\
#define MAX 100

int global_var = 42;

struct point {
    int x, y;
};
"""

KERNEL_STYLE = """\
static int __init my_init(void)
{
    return 0;
}

void __exit my_exit(void)
{
}
"""

IF_STATEMENT_NOT_FUNC = """\
int main(void) {
    if (x > 0) {
        return 1;
    }
    return 0;
}
"""

PREPROCESSOR_MIXED = """\
#include <linux/kernel.h>

ssize_t my_read(struct file *filp, char __user *buf, size_t count, loff_t *offp)
{
    if (count == 0)
        return 0;
    return count;
}
"""


class TestParseFunctions:
    def test_simple_function(self):
        funcs = parse_functions(SIMPLE_FUNC)
        assert len(funcs) == 1
        assert funcs[0].name == "add"
        assert funcs[0].start_line >= 3
        assert funcs[0].end_line >= 5

    def test_two_functions(self):
        funcs = parse_functions(TWO_FUNCS)
        names = {f.name for f in funcs}
        assert names == {"first", "second"}

    def test_multiline_signature(self):
        funcs = parse_functions(MULTILINE_SIG)
        assert len(funcs) == 1
        assert funcs[0].name == "my_function"

    def test_no_function_returns_empty(self):
        funcs = parse_functions(NO_FUNC)
        assert funcs == []

    def test_kernel_style_init_exit(self):
        funcs = parse_functions(KERNEL_STYLE)
        names = {f.name for f in funcs}
        assert "my_init" in names
        assert "my_exit" in names

    def test_if_statement_not_detected_as_function(self):
        funcs = parse_functions(IF_STATEMENT_NOT_FUNC)
        assert len(funcs) == 1
        assert funcs[0].name == "main"

    def test_preprocessor_mixed(self):
        funcs = parse_functions(PREPROCESSOR_MIXED)
        assert len(funcs) == 1
        assert funcs[0].name == "my_read"

    def test_does_not_match_control_keywords(self):
        code = """\
void test(void) {
    if (x) {
        for (int i = 0; i < 10; i++) {
            while (y) { }
        }
    }
}"""
        funcs = parse_functions(code)
        assert len(funcs) == 1
        assert funcs[0].name == "test"

    def test_empty_source(self):
        assert parse_functions("") == []

    def test_line_numbers_are_1_based(self):
        funcs = parse_functions(SIMPLE_FUNC)
        assert funcs[0].start_line >= 1
        assert funcs[0].end_line >= funcs[0].start_line

    def test_braces_in_params_not_confused(self):
        code = """\
void callback(void (*fn)(struct foo { int x; } *)) {
    fn(NULL);
}"""
        funcs = parse_functions(code)
        assert len(funcs) == 1
        assert funcs[0].name == "callback"

    def test_skips_comments_between_funcs(self):
        code = """\
int first(void) {
    return 1;
}
/* comment */
int second(void) {
    return 2;
}"""
        funcs = parse_functions(code)
        assert len(funcs) == 2

    def test_void_pointer_return(self):
        """Regex parser requires a space after * in return type: ``void * alloc``."""
        code = """\
void * alloc(size_t n) {
    return malloc(n);
}"""
        funcs = parse_functions(code)
        assert len(funcs) == 1
        assert funcs[0].name == "alloc"

    def test_const_pointer_return(self):
        """Regex parser requires spaces around * in return type."""
        code = """\
const char * get_name(void) {
    return "foo";
}"""
        funcs = parse_functions(code)
        assert len(funcs) == 1
        assert funcs[0].name == "get_name"
