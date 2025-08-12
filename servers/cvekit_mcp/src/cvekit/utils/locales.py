import os
import gettext
import locale

def load_local_language():
    dir = os.path.dirname(__file__)
    local_path = 'locales'
    language_dir = os.path.join(dir, '../', local_path)
    suported_languages = os.listdir(language_dir)
    language = os.environ.get('LANG', 'en_US')
    language = language.replace('-', '_')
    for sl in suported_languages:
        if sl in language:
            language = sl
            break
    if language not in suported_languages:
        language = 'en_US'
    trans = gettext.translation('messages', language_dir, languages=[language])
    trans.install()
    return trans


def update_docstring(doc):
    def decorator(func):
        func.__doc__ = doc
        return func
    return decorator


i18n = load_local_language().gettext
