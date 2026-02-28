import argparse
import html as html_lib
import os
import re
from pathlib import Path

import requests

MAN7_BASE = "https://man7.org/linux/man-pages/man{section}/{name}.{section}.html"


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text)


def _normalize_pre_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    out_lines = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                out_lines.append("")
            blank = True
        else:
            out_lines.append(line)
            blank = False
    return "\n".join(out_lines)


def extract_section(html: str, section_id: str) -> str | None:
    h2_re = re.compile(
        rf"<h2[^>]*>\s*<a id=\"{re.escape(section_id)}\"[^>]*>.*?</h2>",
        re.IGNORECASE | re.DOTALL,
    )
    match = h2_re.search(html)
    if not match:
        return None
    pre_start = html.find("<pre", match.end())
    if pre_start == -1:
        return None
    pre_open_end = html.find(">", pre_start)
    if pre_open_end == -1:
        return None
    pre_end = html.find("</pre>", pre_open_end)
    if pre_end == -1:
        return None
    raw = html[pre_open_end + 1 : pre_end]
    return _normalize_pre_text(_strip_tags(raw))


def parse_sections(html: str, sections: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sec in sections:
        text = extract_section(html, sec)
        if text:
            out[sec] = text
    return out


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def render_sections(sections: dict[str, str], max_section_chars: int) -> str:
    blocks = []
    for sec, text in sections.items():
        text = truncate_text(text, max_section_chars)
        blocks.append(f"{sec}\n{text}")
    return "\n\n".join(blocks)

def find_manpage_url(name, sections=range(1, 10), timeout=5):
    for sec in sections:
        url = MAN7_BASE.format(section=sec, name=name)
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200:
                return url
        except requests.RequestException:
            continue
    return None

def fetch_manual_html(name, out_dir="manuals"):
    url = find_manpage_url(name)
    if not url:
        raise RuntimeError(f"man7 not found for: {name}")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(r.text)
    return out_path, url