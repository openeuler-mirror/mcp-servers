import os
import gettext
import locale


def load_local_language():
    """
    加载本地化翻译；如果找不到 locales 目录或 .mo 文件，则优雅降级为原文输出。
    """
    base_dir = os.path.dirname(__file__)
    local_path = "locales"
    language_dir = os.path.join(base_dir, "..", local_path)

    # 默认语言从环境变量读取
    language = os.environ.get("LANG", "en_US").replace("-", "_")

    # 收集可用语言目录；如果目录不存在则视为无翻译，使用空列表
    try:
        supported = [
            name
            for name in os.listdir(language_dir)
            if os.path.isdir(os.path.join(language_dir, name))
        ]
    except FileNotFoundError:
        supported = []

    # 尝试在 supported 中找到与当前语言前缀匹配的语言
    for sl in supported:
        if sl in language:
            language = sl
            break

    if language not in supported:
        language = "en_US"

    try:
        trans = gettext.translation("messages", language_dir, languages=[language])
    except FileNotFoundError:
        # 没有找到对应的翻译文件时，使用空翻译，直接返回原文
        trans = gettext.NullTranslations()

    trans.install()
    return trans


def update_docstring(doc):
    def decorator(func):
        func.__doc__ = doc
        return func

    return decorator


i18n = load_local_language().gettext
