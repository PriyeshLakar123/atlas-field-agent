"""Markdown aware chunking.

Splits on headings first so each chunk keeps its section title (which
matters a lot for retrieval on runbooks), then packs paragraphs up to a
character budget with a small overlap.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    section: str
    text: str


def _sections(markdown: str) -> list[tuple[str, str]]:
    title = ""
    trail: list[str] = []
    current: list[str] = []
    out: list[tuple[str, str]] = []
    for line in markdown.splitlines():
        m = _HEADING.match(line)
        if m:
            if "\n".join(current).strip():
                out.append((" > ".join(trail) or title, "\n".join(current).strip()))
            level = len(m.group(1))
            trail = trail[: level - 1] + [m.group(2).strip()]
            if level == 1:
                title = m.group(2).strip()
            current = []
        else:
            current.append(line)
    if "\n".join(current).strip():
        out.append((" > ".join(trail) or title, "\n".join(current).strip()))
    return out


def chunk_markdown(markdown: str, source: str, max_chars: int = 900, overlap: int = 120) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body in _sections(markdown):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        buf = ""
        pieces: list[str] = []
        for para in paragraphs:
            if buf and len(buf) + len(para) + 2 > max_chars:
                pieces.append(buf)
                buf = buf[-overlap:] + "\n\n" + para if overlap else para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            pieces.append(buf)
        for i, piece in enumerate(pieces):
            text = f"{section}\n\n{piece}" if section else piece
            digest = hashlib.sha1(f"{source}|{section}|{i}".encode()).hexdigest()[:16]
            chunks.append(Chunk(chunk_id=digest, source=source, section=section, text=text))
    return chunks


def chunk_directory(path: str | Path) -> list[Chunk]:
    root = Path(path)
    out: list[Chunk] = []
    for file in sorted(root.rglob("*.md")):
        out.extend(chunk_markdown(file.read_text(encoding="utf-8"), source=file.relative_to(root).as_posix()))
    return out
