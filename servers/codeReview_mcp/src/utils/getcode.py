import os
import re
import json
import argparse
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

@dataclass
class CodeElement:
    type: str  # 'function', 'struct', 'macro', 'globalvar'
    name: str
    file: str
    lineno: Tuple[int, int]  # (start, end)
    code: str

class CCodeExtractor:
    def __init__(self):
        self.elements: Dict[str, Dict[str, Dict[str, Any]]] = {
            'function': {},
            'struct': {},
            'macro': {},
            'globalvar': {},
            'enum': {}
        }
        self.files_scanned = 0

    def scan_directory(self, root_dir: str) -> None:
        """递归扫描目录下的所有.c和.h文件"""
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.endswith(('.c', '.h')):
                    file_path = os.path.join(root, file)
                    self.scan_file(file_path)

    def scan_file(self, file_path: str) -> None:
        """扫描单个文件并提取代码要素"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
                self.files_scanned += 1

                # 提取各种代码要素
                self._extract_functions(file_path, content, lines)
                self._extract_structs(file_path, content, lines)
                self._extract_macros(file_path, content, lines)
                self._extract_global_vars(file_path, content, lines)
                self._extract_enums(file_path, content, lines)

        except UnicodeDecodeError:
            print(f"Warning: Could not read file {file_path} (encoding issue)")
        except Exception as e:
            print(f"Error scanning file {file_path}: {e}")

    def _extract_functions(self, file_path: str, content: str, lines: List[str]) -> None:
        """提取函数定义（只提取有实现的，忽略声明）"""
        # 改进后的正则表达式，匹配更多函数定义格式
        pattern = re.compile(
            #r'^(?:(?:\w+\s+)+)?'      # 返回类型和可能的修饰符（如static inline）
            r'^(?:(?:[\w*]+\s+)+)?'
            r'(\w+)'                  # 函数名
            r'\s*\([\s\S]*?\)'           # 参数列表
            r'\s*\{',                 # 函数体开始
            re.MULTILINE
        )
        
        for match in pattern.finditer(content):
            func_name = match.group(1)
            start_line = content[:match.start()].count('\n') + 1
            try:
                code_block, end_line = self._get_code_block(lines, start_line - 1)
                if code_block and '{' in code_block:  # 确保是有效的函数实现
                    self.elements['function'][func_name] = {
                        'file': file_path,
                        'lineno': [start_line, end_line],
                        'code': code_block
                    }
            except Exception as e:
                print(f"Error processing function {func_name} at line {start_line}: {e}")

    def _extract_structs(self, file_path: str, content: str, lines: List[str]) -> None:
        """提取结构体定义（只提取有定义的，忽略声明）"""
        # 匹配结构体定义（有定义的）
        pattern = re.compile(
            r'^\s*(?:typedef\s+)?(?:struct|union)\s+(\w+)\s*\{',
            re.MULTILINE
        )

        for match in pattern.finditer(content):
            struct_name = match.group(1)
            start_line = content[:match.start()].count('\n') + 1
            code_block, end_line = self._get_code_block(lines, start_line - 1)
            
            # 确保是定义而不是声明
            if '{' in code_block and '}' in code_block:
                self.elements['struct'][struct_name] = {
                    'file': file_path,
                    'lineno': [start_line, end_line],
                    'code': code_block
                }

    def _extract_macros(self, file_path: str, content: str, lines: List[str]) -> None:
        """提取宏定义"""
        # 匹配宏定义
        #r'^\s*#\s*define\s+(\w+)',
        pattern = re.compile(
            r'#\s*define\s+(\w+)',
            re.MULTILINE
        )

        for match in pattern.finditer(content):
            macro_name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            lines_cnt = content.count('\n')
            code_line = lines[line_num].strip()
            code_block, end_line = self._get_macro_block(lines, line_num - 1)
            self.elements['macro'][macro_name] = {
                'file': file_path,
                'lineno': [line_num, end_line],
                'code': code_block
            }
                

    def _extract_global_vars(self, file_path: str, content: str, lines: List[str]) -> None:
        """提取全局变量（只提取有定义的，忽略声明）"""
        # 匹配全局变量定义（有初始化的更可能是定义）
        pattern = re.compile(
            r'^(?!\s*(?:inline|#|//|/\*|\w+$.*$\s*\{))'  # 排除局部变量和函数
            r'(?:\w+\s+)+'  # 类型
            r'(\w+)'        # 变量名
            r'(?:\s*\[\w*\]\s*)*'
            r'\s*=[^;]*;',  # 有初始化的更可能是定义
            re.MULTILINE
        )

        for match in pattern.finditer(content):
            var_name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            line_end = content[:match.end()].count('\n') + 1
            code_block = ""
            for idx in range(line_num, line_end + 1):
                code_block += lines[idx - 1].strip()
            
            self.elements['globalvar'][var_name] = {
                'file': file_path,
                'lineno': [line_num, line_end],
                'code': code_block
            }

    def _extract_enums(self, file_path: str, content: str, lines: List[str]) -> None:
        """提取枚举定义"""
        # 匹配枚举定义
        pattern = re.compile(
            r'^\s*(?:typedef\s+)?(?:enum)\s+(\w+)\s*\{',
            re.MULTILINE
        )

        for match in pattern.finditer(content):
            enum_name = match.group(1)
            start_line = content[:match.start()].count('\n') + 1
            code_block, end_line = self._get_code_block(lines, start_line - 1)
            
            # 确保是定义而不是声明
            if '{' in code_block and '}' in code_block:
                self.elements['enum'][enum_name] = {
                    'file': file_path,
                    'lineno': [start_line, end_line],
                    'code': code_block
                }
    
    def _get_code_block(self, lines: List[str], start_idx: int) -> Tuple[str, int]:
        """获取从指定行开始的代码块"""
        if start_idx >= len(lines):
            return "", start_idx
            
        brace_count = 0
        end_idx = start_idx
        
        # 查找第一个左大括号
        while end_idx < len(lines):
            line = lines[end_idx]
            if '{' in line:
                brace_count += line.count('{')
                break
            end_idx += 1
        else:
            return "", start_idx  # 没有找到左大括号
        
        # 匹配大括号
        while end_idx < len(lines) and brace_count > 0:
            end_idx += 1
            if end_idx >= len(lines):
                break
            line = lines[end_idx]
            brace_count += line.count('{')
            brace_count -= line.count('}')
        
        # 确保end_idx不越界
        end_idx = min(end_idx, len(lines) - 1)
        code_block = '\n'.join(lines[start_idx:end_idx + 1])
        return code_block.strip(), end_idx + 1

    def _get_macro_block(self, lines: List[str], start_idx: int) -> Tuple[str, int]:
        """获取宏定义的完整代码块（可能跨多行）"""
        end_idx = start_idx
        line = lines[end_idx]
        
        # 检查是否以反斜杠结束（表示续行）
        while end_idx < len(lines) and line.rstrip().endswith('\\'):
            end_idx += 1
            if end_idx >= len(lines):
                break
            line = lines[end_idx]
        
        code_block = '\n'.join(lines[start_idx:end_idx + 1])
        return code_block.strip(), end_idx + 1

    def to_dict(self) -> Dict[str, Any]:
        """将提取的元素转换为字典格式"""
        return {
            'function': self.elements['function'],
            'struct': self.elements['struct'],
            'macro': self.elements['macro'],
            'globalvar': self.elements['globalvar'],
            'enum': self.elements['enum'],
            'stats': {
                'files_scanned': self.files_scanned,
                'functions': len(self.elements['function']),
                'structs': len(self.elements['struct']),
                'macros': len(self.elements['macro']),
                'globalvars': len(self.elements['globalvar']),
                'enums': len(self.elements['enum'])
            }
        }

def save_to_json(data: Dict[str, Any], output_file: str) -> None:
    """将数据保存到JSON文件"""
    print(output_file)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_from_json(json_file: str) -> Dict[str, Any]:
    """从JSON文件加载数据"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def gen_project_rag(path: str, json: str):
    extractor = CCodeExtractor()
    print(f"Scanning directory: {path}")
    extractor.scan_directory(path)
    data = extractor.to_dict()
    save_to_json(data, json)
    print(f"Saved {json} with {data['stats']['files_scanned']} files scanned")
    print(f"Found {data['stats']['functions']} functions, {data['stats']['structs']} structs, "
            f"{data['stats']['macros']} macros, {data['stats']['globalvars']} global variables, "
            f"{data['stats']['enums']} enums")

def get_project_rag(
    json: str,
    func: str=None,
    struct: str=None,
    macro: str=None,
    globalvar: str=None,
    enum: str=None
):
    data = load_from_json(json)
    result = []
    if func:
        etype = 'function'
        if func in data['function']:
            element = data['function'].get(func)
        elif func in data['macro']:
            element = data['macro'].get(func)
            etype = 'Macro'
        result.append(get_result(etype, func, element))
    if struct:
        element = data['struct'].get(struct)
        result.append(get_result('Struct', struct, element))
    if macro:
        etype = 'Macro'
        if macro in data['macro']:
            element = data['macro'].get(macro)
        else:
            for key, each in data[''].items():
                if macro not in each['code']:
                    continue
                element = each
                etype = 'Enum'
                break
        result.append(get_result(etype, macro, element))
    if globalvar:
        element = data['globalvar'].get(globalvar)
        result.append(get_result('Global Variable', globalvar, element))
    if enum:
        element = data['enum'].get(enum)
        result.append(get_result('Enum', enum, element))
    return result

def main():
    parser = argparse.ArgumentParser(description='C语言代码要素提取与查询工具')
    parser.add_argument('--path', help='要扫描的代码目录')
    parser.add_argument('--output', help='输出的JSON文件路径')
    parser.add_argument('--json', help='要查询的JSON文件路径')
    parser.add_argument('--func', help='查询指定函数')
    parser.add_argument('--struct', help='查询指定结构体')
    parser.add_argument('--macro', help='查询指定宏')
    parser.add_argument('--enum', help='查询枚举')
    parser.add_argument('--globalvar', help='查询指定全局变量')
    args = parser.parse_args()

    if args.path and args.output:
        # 扫描代码并生成JSON文件
        gen_project_rag(args.path, args.output)
    elif args.json and (args.func or args.struct or args.macro or args.globalvar):
        # 从JSON文件查询
        code = get_project_rag(args.json, func=args.func,
                               struct=args.struct, macro=args.macro, 
                               globalvar=args.globalvar)
        print(code)
    else:
        parser.print_help()

def get_result(element_type: str, name: str, element: Optional[Dict[str, Any]]) -> None:
    """打印查询结果"""
    res = {}
    if element:
        res["name"] = name
        res["type"] = element_type
        res["code"] = element["code"]
        res["line"] = element["lineno"]
    else:
        res["notfound"] = 1
        #print(f"Not found: {element_type} '{name}' in the index")
    return res

if __name__ == '__main__':
    main()
