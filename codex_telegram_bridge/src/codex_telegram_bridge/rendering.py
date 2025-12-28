from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from markdown_it import MarkdownIt
from sulguk import transform_html

def render_markdown(md: str) -> Tuple[str, List[Dict[str, Any]]]:
    html = MarkdownIt("commonmark", {"html": False}).render(md or "")
    rendered = transform_html(html)

    text = re.sub("(?m)^(\\s*)\u2022", r"\1-", rendered.text)

    # FIX: Telegram requires MessageEntity.language (if present) to be a String.
    entities: List[Dict[str, Any]] = []
    for e in rendered.entities:
        d = dict(e)
        if "language" in d and not isinstance(d["language"], str):
            d.pop("language", None)
        entities.append(d)
    return text, entities


def _chunk_text_with_indices(text: str, limit: int) -> List[Tuple[str, int, int]]:
    text = text or ""
    if len(text) <= limit:
        return [(text, 0, len(text))]

    out: List[Tuple[str, int, int]] = []
    buf: List[str] = []
    size = 0
    buf_start = 0
    pos = 0

    for line in text.splitlines(keepends=True):
        line_len = len(line)
        line_start = pos
        line_end = pos + line_len

        if line_len > limit:
            if buf:
                out.append(("".join(buf), buf_start, line_start))
                buf, size = [], 0
            for i in range(0, line_len, limit):
                part = line[i : i + limit]
                out.append((part, line_start + i, line_start + i + len(part)))
            pos = line_end
            buf_start = pos
            continue

        if size + line_len > limit:
            out.append(("".join(buf), buf_start, line_start))
            buf = [line]
            size = line_len
            buf_start = line_start
        else:
            if not buf:
                buf_start = line_start
            buf.append(line)
            size += line_len

        pos = line_end

    if buf:
        out.append(("".join(buf), buf_start, pos))
    return out


def _slice_entities(entities: List[Dict[str, Any]], start: int, end: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ent in entities:
        try:
            ent_start = int(ent.get("offset", 0))
            ent_len = int(ent.get("length", 0))
        except (TypeError, ValueError):
            continue
        if ent_len <= 0:
            continue
        ent_end = ent_start + ent_len
        if ent_end <= start or ent_start >= end:
            continue
        new_start = max(ent_start, start)
        new_end = min(ent_end, end)
        new_len = new_end - new_start
        if new_len <= 0:
            continue
        new_ent = dict(ent)
        new_ent["offset"] = new_start - start
        new_ent["length"] = new_len
        out.append(new_ent)
    return out
