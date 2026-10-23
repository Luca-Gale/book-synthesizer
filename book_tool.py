#!/usr/bin/env python3
"""
book_tool.py — Local PDF, Obsidian Vault & AnkiConnect Toolkit for Book-Synthesizer.

Designed to be orchestrated by Antigravity (zero external LLM API keys required).
Provides six deterministic commands:
  1. status        : Inspect active PDF in ./book/, target chapter in ./chapter.txt, and AnkiConnect status
  2. prepare       : Extract ToC/sections for the target chapter and render 300-DPI page PNGs
  3. crop          : Crop a figure bounding box [ymin, xmin, ymax, xmax] with 5% padding into vault assets
  4. finalize      : Sanitize MathJax, wire [[Prev]]/[[MOC]]/[[Next]] links, build MOC, & sync Anki cards
  5. sync-anki     : Aggregate section flashcards into ./decks/ and sync non-destructively via AnkiConnect
  6. refresh-cards : Inspect existing Obsidian notes & card ledgers to refresh flashcards without re-synthesizing notes
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_NOTES_MARKER = "<!-- USER NOTES BELOW THIS LINE -->"
ORPHAN_TAG = "book_synthesizer::orphaned"


def load_config(workspace_root: Path) -> dict[str, Any]:
    config_path = workspace_root / "config.json"
    default_cfg = {
        "book_dir": "./book",
        "chapter_file": "./chapter.txt",
        "vault_dir": "./vault",
        "decks_dir": "./decks",
        "cache_dir": "./.cache",
        "anki_connect_url": "http://127.0.0.1:8765",
        "anki_deck_root": "Textbooks",
        "anki_basic_model": "Basic",
        "anki_cloze_model": "Cloze",
        "render_dpi": 300,
        "crop_padding_pct": 0.05,
        "skip_section_keywords": [
            "bibliography",
            "references",
            "problems",
            "exercises",
            "further reading",
            "historical notes",
            "appendix",
            "solutions",
            "acknowledgements",
            "index",
        ],
    }
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        default_cfg.update(loaded)
    return default_cfg


def sanitize_filename(name: str) -> str:
    """Convert raw section/chapter titles into Windows & Obsidian safe filenames."""
    cleaned = re.sub(r"[—–:/\\|?*\"<>]", " - ", name)
    cleaned = re.sub(r"\s*-\s*-\s*", " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return cleaned


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug or "book"


def find_active_pdf(book_dir: Path) -> Path:
    if not book_dir.exists():
        book_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(
        book_dir.glob("*.pdf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not pdfs:
        raise FileNotFoundError(
            f"No PDF file found in '{book_dir.resolve()}'. "
            "Please drag and drop your textbook PDF into the 'book/' folder."
        )
    return pdfs[0]


def read_target_chapter(chapter_file: Path) -> str:
    if not chapter_file.exists():
        chapter_file.write_text("1\n", encoding="utf-8")
        return "1"
    raw = chapter_file.read_text(encoding="utf-8").strip()
    m = re.search(r"(\d+)", raw)
    if not m:
        raise ValueError(
            f"Could not find a chapter number in '{chapter_file}'. "
            "Please write a single chapter number (e.g. '1' or '3') in chapter.txt."
        )
    return m.group(1)


def should_skip_section(title: str, skip_keywords: list[str]) -> bool:
    lower_title = title.lower()
    return any(kw.lower() in lower_title for kw in skip_keywords)


def parse_toc_for_chapter(
    toc: list[list[Any]], target_ch: str, total_pages: int, skip_keywords: list[str]
) -> dict[str, Any] | None:
    if not toc:
        return None

    ch_pattern = re.compile(
        rf"^(?:chapter\s+)?0*{re.escape(target_ch)}(?:\b|[\s.:—–-])(.*)$",
        re.IGNORECASE,
    )
    sec_pattern = re.compile(
        rf"^0*{re.escape(target_ch)}\.(\d+)\b[\s.:—–-]*(.*)$"
    )

    ch_idx = None
    ch_level = None
    ch_title = f"Chapter {target_ch}"
    ch_start_page = None
    ch_end_page = total_pages

    for i, (lvl, title, page) in enumerate(toc):
        clean_t = title.strip()
        if re.match(rf"^0*{re.escape(target_ch)}\.\d+", clean_t):
            continue
        m = ch_pattern.match(clean_t)
        if m and page >= 1:
            ch_idx = i
            ch_level = lvl
            suffix = m.group(1).strip(" .:;-—–")
            ch_title = suffix if suffix else f"Chapter {target_ch}"
            ch_start_page = page
            break

    if ch_idx is None:
        return None

    for j in range(ch_idx + 1, len(toc)):
        lvl, _title, page = toc[j]
        if lvl <= ch_level and page >= ch_start_page:
            ch_end_page = max(ch_start_page, page - 1)
            break

    raw_sections: list[dict[str, Any]] = []
    for j in range(ch_idx + 1, len(toc)):
        lvl, title, page = toc[j]
        if lvl <= ch_level:
            break
        clean_t = " ".join(title.strip().split())
        m_sec = sec_pattern.match(clean_t)
        if m_sec:
            sec_num = f"{target_ch}.{m_sec.group(1)}"
            sec_name = m_sec.group(2).strip(" .:;-—–") or f"Section {sec_num}"
            raw_sections.append(
                {
                    "section_number": sec_num,
                    "title": sec_name,
                    "start_pdf_page": page,
                    "skipped": should_skip_section(sec_name, skip_keywords),
                }
            )

    for idx, sec in enumerate(raw_sections):
        if idx + 1 < len(raw_sections):
            next_start = raw_sections[idx + 1]["start_pdf_page"]
            sec["end_pdf_page"] = max(sec["start_pdf_page"], next_start)
        else:
            sec["end_pdf_page"] = ch_end_page

    return {
        "chapter_number": target_ch,
        "chapter_title": ch_title,
        "start_pdf_page": ch_start_page,
        "end_pdf_page": ch_end_page,
        "sections": raw_sections,
    }


def scan_text_for_chapter_sections(
    doc: Any, target_ch: str, skip_keywords: list[str]
) -> dict[str, Any]:
    sec_heading_re = re.compile(
        rf"(?m)^\s*({re.escape(target_ch)}\.[1-9]\d*)\s+([A-Z][^\n\r{{}}0-9]{{2,90}}?)(?:\s+(\d{{1,4}}))?\s*$"
    )
    toc_pages: list[int] = []
    section_hits: dict[str, dict[str, Any]] = {}

    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text("text")
        if re.search(r"\b(contents|table of contents)\b", text, re.IGNORECASE) and page_idx < 30:
            toc_pages.append(page_idx + 1)

        for match in sec_heading_re.finditer(text):
            sec_num = match.group(1)
            sec_title = " ".join(match.group(2).split()).strip(" .…-")
            trailing_page = match.group(3)
            if not trailing_page and sec_num not in section_hits:
                section_hits[sec_num] = {
                    "section_number": sec_num,
                    "title": sec_title,
                    "start_pdf_page": page_idx + 1,
                    "skipped": should_skip_section(sec_title, skip_keywords),
                }

    sorted_secs = sorted(
        section_hits.values(),
        key=lambda s: [int(x) for x in s["section_number"].split(".")],
    )
    for i, sec in enumerate(sorted_secs):
        if i + 1 < len(sorted_secs):
            sec["end_pdf_page"] = max(
                sec["start_pdf_page"], sorted_secs[i + 1]["start_pdf_page"]
            )
        else:
            sec["end_pdf_page"] = min(len(doc), sec["start_pdf_page"] + 4)

    if sorted_secs:
        start_p = max(1, sorted_secs[0]["start_pdf_page"] - 1)
        end_p = sorted_secs[-1]["end_pdf_page"]
    else:
        start_p = 1
        end_p = min(len(doc), 20)

    return {
        "chapter_number": target_ch,
        "chapter_title": f"Chapter {target_ch}",
        "start_pdf_page": start_p,
        "end_pdf_page": end_p,
        "toc_pdf_pages": toc_pages[:10],
        "sections": sorted_secs,
    }


def render_pdf_pages(
    doc: Any, start_page: int, end_page: int, out_dir: Path, dpi: int
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []
    start_p = max(1, start_page)
    end_p = min(len(doc), end_page)

    for p_num in range(start_p, end_p + 1):
        page = doc[p_num - 1]
        img_path = out_dir / f"pdf_page_{p_num:04d}.png"
        txt_path = out_dir / f"pdf_page_{p_num:04d}.txt"
        if not img_path.exists():
            pix = page.get_pixmap(dpi=dpi)
            pix.save(str(img_path))
        if not txt_path.exists():
            txt_path.write_text(page.get_text("text"), encoding="utf-8")
        rendered.append(
            {
                "pdf_page": p_num,
                "page_label": page.get_label() or str(p_num),
                "image_path": str(img_path.resolve()),
                "text_path": str(txt_path.resolve()),
            }
        )
    return rendered


def get_vault_chapter_dir(
    workspace_root: Path, cfg: dict[str, Any], book_name: str, ch_num: str, ch_title: str
) -> Path:
    vault_root = (workspace_root / cfg["vault_dir"]).resolve()
    clean_book = sanitize_filename(book_name)
    clean_ch_title = sanitize_filename(ch_title)
    if clean_ch_title.lower() == f"chapter {ch_num}".lower():
        folder_name = f"Chapter {int(ch_num):02d}"
    else:
        folder_name = f"Chapter {int(ch_num):02d} - {clean_ch_title}"
    return vault_root / clean_book / folder_name


def get_deck_ledger_path(
    workspace_root: Path, cfg: dict[str, Any], book_slug: str, ch_num: str
) -> Path:
    decks_root = (workspace_root / cfg.get("decks_dir", "./decks")).resolve()
    book_decks_dir = decks_root / book_slug
    book_decks_dir.mkdir(parents=True, exist_ok=True)
    return book_decks_dir / f"ch_{int(ch_num):02d}_cards.json"


# ============================================================================
# AnkiConnect Client & MathJax / HTML Formatting Engine
# ============================================================================

def anki_request(url: str, action: str, timeout: float = 5.0, **params: Any) -> Any:
    """Invoke AnkiConnect HTTP API on localhost."""
    payload: dict[str, Any] = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if len(data) != 2:
        raise RuntimeError(f"Unexpected AnkiConnect response format: {data}")
    if data.get("error") is not None:
        raise RuntimeError(f"AnkiConnect error in '{action}': {data['error']}")
    return data.get("result")


def check_anki_connection(url: str) -> bool:
    """Return True if Anki is running with AnkiConnect listening."""
    try:
        ver = anki_request(url, "version", timeout=2.0)
        return ver is not None
    except Exception:
        return False


def resolve_anki_models(url: str, cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Query AnkiConnect for available note types and their exact field names.
    Handles English ('Basic', 'Cloze') and localized Anki installs (e.g. Italian 'Basilare', 'Base', 'Omissione').
    """
    model_names: list[str] = anki_request(url, "modelNames") or []
    pref_basic = cfg.get("anki_basic_model", "Basic")
    pref_cloze = cfg.get("anki_cloze_model", "Cloze")

    basic_candidates = [pref_basic, "Basic", "Basilare", "Base", "Basic (and reversed card)"]
    cloze_candidates = [pref_cloze, "Cloze", "Omissione", "Cloze (overlapping)"]

    chosen_basic = None
    for cand in basic_candidates:
        for m in model_names:
            if m.lower() == cand.lower():
                chosen_basic = m
                break
        if chosen_basic:
            break
    if not chosen_basic:
        for m in model_names:
            if "basic" in m.lower() or "basilar" in m.lower() or "base" in m.lower():
                chosen_basic = m
                break
    if not chosen_basic and model_names:
        chosen_basic = model_names[0]

    chosen_cloze = None
    for cand in cloze_candidates:
        for m in model_names:
            if m.lower() == cand.lower():
                chosen_cloze = m
                break
        if chosen_cloze:
            break
    if not chosen_cloze:
        for m in model_names:
            if "cloze" in m.lower() or "omission" in m.lower():
                chosen_cloze = m
                break
    if not chosen_cloze and chosen_basic:
        chosen_cloze = chosen_basic

    result: dict[str, dict[str, Any]] = {}
    for logical_name, actual_name in [("Basic", chosen_basic), ("Cloze", chosen_cloze)]:
        if not actual_name:
            raise RuntimeError("No valid note models found in Anki profile.")
        fields: list[str] = anki_request(url, "modelFieldNames", modelName=actual_name) or []
        if len(fields) < 2:
            raise RuntimeError(f"Anki model '{actual_name}' has fewer than 2 fields: {fields}")
        result[logical_name] = {
            "model_name": actual_name,
            "front_field": fields[0],
            "back_field": fields[1],
            "all_fields": fields,
        }
    return result


def make_anki_media_filename(book_slug: str, ch_num: str, raw_filename: str) -> str:
    clean_name = Path(raw_filename).name
    prefix = f"{book_slug}_ch{int(ch_num):02d}_"
    if clean_name.startswith(prefix):
        return clean_name
    return f"{prefix}{clean_name}"


def _escape_math_for_anki_html(math_inner: str) -> str:
    """
    Escape &, <, > inside MathJax expressions so Anki's HTML DOM parser does not
    interpret `< y` or matrix `&` as HTML tags or broken entities.
    """
    s = re.sub(r"&(?!(?:amp|lt|gt|quot|#\d+);)", "&amp;", math_inner)
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    if s.endswith("}"):
        s += " "
    return s


def _split_math_by_balanced_clozes(math_str: str) -> list[tuple[bool, str]]:
    """
    Parse a math expression that may contain `{{c1::...}}` or `{{c2::...}}` with nested LaTeX `{...}` braces.
    Returns a list of `(is_cloze, content)` segments so that `{{c1::...}}` can be hoisted OUTSIDE `\\(...\\)`.
    Why? In Anki 23.10+/24+, putting `{{c1::...}}` INSIDE `\\[...\\]` or `\\(...\\)` suppresses the `<span class="cloze" data-cloze="...">`
    DOM element, which breaks the editor preview! Putting `\\(...\\)` INSIDE `{{c1::\\(...\\)}}` guarantees both
    a valid `<span class="cloze" data-cloze="...">` AND eliminates `}}}` brace collisions!
    """
    segments: list[tuple[bool, str]] = []
    cloze_start_re = re.compile(r"\{\{c\d+::")
    pos = 0
    n = len(math_str)

    while pos < n:
        m = cloze_start_re.search(math_str, pos)
        if not m:
            rem = math_str[pos:]
            if rem:
                segments.append((False, rem))
            break

        if m.start() > pos:
            segments.append((False, math_str[pos : m.start()]))

        # Scan forward from m.end() balancing single `{` and `}` until we hit closing `}}` at depth 0
        idx = m.end()
        brace_depth = 0
        cloze_end_inner = None
        while idx < n:
            if math_str[idx] == "\\" and idx + 1 < n and math_str[idx + 1] in "{}":
                idx += 2
                continue
            if math_str[idx] == "{":
                brace_depth += 1
                idx += 1
            elif math_str[idx] == "}":
                if brace_depth > 0:
                    brace_depth -= 1
                    idx += 1
                elif idx + 1 < n and math_str[idx + 1] == "}":
                    cloze_end_inner = idx
                    idx += 2
                    break
                else:
                    idx += 1
            else:
                idx += 1

        if cloze_end_inner is not None:
            segments.append((True, math_str[m.end() : cloze_end_inner]))
            pos = idx
        else:
            # Fallback if unclosed
            segments.append((False, math_str[m.start() :]))
            break

    return segments


def _format_math_block_for_anki(math_inner: str, is_display: bool) -> str:
    """
    Format a math block for Anki:
    - If it contains no `{{cN::...}}`, wrap in `\\[...\\]` (display) or `\\(...\\)` (inline).
    - If it contains `{{cN::...}}`, hoist `{{c1::...}}` OUTSIDE the MathJax delimiters so Anki always
      renders `<span class="cloze" data-cloze="...">` and never suffers from `}}}` LaTeX brace collisions.
    """
    stripped = math_inner.strip()
    if not re.search(r"\{\{c\d+::", stripped):
        esc = _escape_math_for_anki_html(stripped)
        return f"\\[{esc}\\]" if is_display else f"\\({esc}\\)"

    segments = _split_math_by_balanced_clozes(stripped)
    # Check if the entire math block is a single cloze
    non_empty = [(is_c, seg.strip()) for is_c, seg in segments if seg.strip()]
    if len(non_empty) == 1 and non_empty[0][0]:
        esc = _escape_math_for_anki_html(non_empty[0][1])
        return f"{{{{c1::\\({esc}\\)}}}}"

    out_parts: list[str] = []
    for is_cloze, seg in segments:
        s = seg.strip()
        if not s:
            continue
        esc = _escape_math_for_anki_html(s)
        if is_cloze:
            out_parts.append(f"{{{{c1::\\({esc}\\)}}}}")
        else:
            out_parts.append(f"\\({esc}\\)")

    joined = " ".join(out_parts)
    return f"<br>{joined}<br>" if is_display else joined


def convert_markdown_and_math_to_anki(
    raw_text: str, book_slug: str, ch_num: str
) -> tuple[str, list[str]]:
    """
    Token-aware converter from Obsidian Markdown + LaTeX ($...$, $$...$$) to Anki HTML + MathJax (\\(...\\), \\[...\\]).
    - Protects fenced and inline code blocks.
    - Extracts Obsidian image embeds ![[assets/fig.png]] or <img src="fig.png"> and rewrites to Anki media filenames.
    - Converts $$...$$ and $...$ to Anki MathJax while hoisting any `{{cN::...}}` outside `\\(...\\)` so Anki's
      Cloze preview always works and `}}}` brace collisions cannot occur.
    - Normalizes all `{{c2::...}}`, `{{c3::...}}` to `{{c1::...}}` so 1 flashcard = 1 card in Anki (never registered twice).
    """
    if not raw_text:
        return "", []

    discovered_media: list[str] = []

    # Step 1: Protect fenced code blocks and inline code
    code_tokens: list[str] = []

    def save_fenced_code(m: re.Match[str]) -> str:
        inner = html.escape(m.group(1).strip())
        code_tokens.append(f"<pre><code>{inner}</code></pre>")
        return f"\x00ANKICODE{len(code_tokens)-1}\x00"

    def save_inline_code(m: re.Match[str]) -> str:
        inner = html.escape(m.group(1))
        code_tokens.append(f"<code>{inner}</code>")
        return f"\x00ANKICODE{len(code_tokens)-1}\x00"

    text = re.sub(r"```(?:\w+)?\n?([\s\S]*?)```", save_fenced_code, raw_text)
    text = re.sub(r"`([^`\n]+?)`", save_inline_code, text)

    # Step 2: Extract & rewrite image embeds: ![[assets/fig.png]] or ![[fig.png]] or <img src="...">
    img_tokens: list[str] = []

    def replace_obsidian_img(m: re.Match[str]) -> str:
        raw_target = m.group(1).split("|")[0].strip()
        base_name = Path(raw_target).name
        if base_name not in discovered_media:
            discovered_media.append(base_name)
        anki_fname = make_anki_media_filename(book_slug, ch_num, base_name)
        img_tokens.append(f'<br><img src="{anki_fname}">')
        return f"\x00ANKIIMG{len(img_tokens)-1}\x00"

    def replace_html_img(m: re.Match[str]) -> str:
        raw_src = m.group(1).strip()
        base_name = Path(raw_src).name
        if base_name not in discovered_media:
            discovered_media.append(base_name)
        anki_fname = make_anki_media_filename(book_slug, ch_num, base_name)
        img_tokens.append(f'<img src="{anki_fname}">')
        return f"\x00ANKIIMG{len(img_tokens)-1}\x00"

    text = re.sub(r"!\[\[([^\]]+?)\]\]", replace_obsidian_img, text)
    text = re.sub(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', replace_html_img, text, flags=re.IGNORECASE)

    # Step 3: Convert \[...\], \(...\), $$...$$, and $...$ using cloze-safe math formatter
    math_tokens: list[str] = []

    def save_display_math(m: re.Match[str]) -> str:
        formatted = _format_math_block_for_anki(m.group(1), is_display=True)
        math_tokens.append(formatted)
        return f"\x00ANKIMATH{len(math_tokens)-1}\x00"

    def save_inline_math(m: re.Match[str]) -> str:
        formatted = _format_math_block_for_anki(m.group(1), is_display=False)
        math_tokens.append(formatted)
        return f"\x00ANKIMATH{len(math_tokens)-1}\x00"

    # Existing \[...\] and \(...\)
    text = re.sub(r"\\\[([\s\S]*?)\\\]", save_display_math, text)
    text = re.sub(r"\\\(([\s\S]*?)\\\)", save_inline_math, text)

    # Display $$...$$
    text = re.sub(r"(?<!\\)\$\$([\s\S]*?)(?<!\\)\$\$", save_display_math, text)

    # Inline $...$ (single line, not preceded or followed by \ or $)
    text = re.sub(r"(?<![\$\\])\$(?!\$)([^\$\n]+?)(?<![\$\\])\$(?!\$)", save_inline_math, text)

    # Unescape literal \$ outside math
    text = text.replace(r"\$", "$")

    # Normalize any remaining {{c2::...}}, {{c3::...}} outside math to {{c1::...}} so 1 note = 1 card
    text = re.sub(r"\{\{c\d+::", "{{c1::", text)

    # Step 4: Convert basic Markdown formatting outside math/code
    text = re.sub(r"\*\*([^\*\n]+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)", r"<i>\1</i>", text)

    # Convert newlines to <br>
    text = text.strip()
    text = re.sub(r"\r?\n", "<br>", text)

    # Step 5: Restore tokens
    for i, mt in enumerate(math_tokens):
        text = text.replace(f"\x00ANKIMATH{i}\x00", mt)
    for i, it in enumerate(img_tokens):
        text = text.replace(f"\x00ANKIIMG{i}\x00", it)
    for i, ct in enumerate(code_tokens):
        text = text.replace(f"\x00ANKICODE{i}\x00", ct)

    # Clean up excessive <br>
    text = re.sub(r"(<br>\s*){3,}", "<br><br>", text)
    text = re.sub(r"^(<br>\s*)+|(<br>\s*)+$", "", text)

    return text, discovered_media


def compute_card_hash(
    subdeck: str, model_type: str, anki_front: str, anki_back: str, tags: list[str]
) -> str:
    payload = json.dumps(
        {
            "subdeck": subdeck,
            "model_type": model_type,
            "front": anki_front,
            "back": anki_back,
            "tags": sorted(set(tags)),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize_model_type(raw_model: str, front_text: str) -> str:
    """Detect whether a card is Basic or Cloze."""
    if re.search(r"\{\{c\d+::", front_text):
        return "Cloze"
    if raw_model and "cloze" in raw_model.lower():
        return "Cloze"
    return "Basic"


def aggregate_chapter_cards(
    workspace_root: Path,
    cfg: dict[str, Any],
    book_name: str,
    ch_num: str,
    section_filter: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Single-threaded aggregator: merges per-section `.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json`
    into the persistent chapter ledger `decks/<book_slug>/ch_<XX>_cards.json`.
    """
    book_slug = slugify(book_name)
    cache_ch_dir = (workspace_root / cfg["cache_dir"] / book_slug / f"ch_{int(ch_num):02d}").resolve()
    ledger_path = get_deck_ledger_path(workspace_root, cfg, book_slug, ch_num)

    clean_book_title = re.sub(r"\s+", " ", sanitize_filename(book_name).replace("_", " ")).strip()
    deck_root = cfg.get("anki_deck_root", "Textbooks")

    # Check if sibling chapter ledgers already established a book deck prefix
    existing_book_prefix: str | None = None
    decks_book_dir = ledger_path.parent
    if decks_book_dir.exists():
        for sibling_ledger in sorted(decks_book_dir.glob("ch_*_cards.json")):
            if sibling_ledger.resolve() == ledger_path.resolve():
                continue
            try:
                s_data = json.loads(sibling_ledger.read_text(encoding="utf-8"))
                p = s_data.get("deck_prefix")
                if p:
                    parts = p.split("::")
                    if len(parts) >= 2:
                        existing_book_prefix = "::".join(parts[:2])
                        break
            except Exception:
                pass

    book_prefix = existing_book_prefix or f"{deck_root}::{clean_book_title}"
    default_deck_prefix = f"{book_prefix}::Chapter {int(ch_num):02d}"

    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        deck_prefix = ledger.get("deck_prefix") or default_deck_prefix
        # If ledger had a stale deck prefix differing only in whitespace from sibling ledger, align it
        if existing_book_prefix and not deck_prefix.startswith(existing_book_prefix):
            parts = deck_prefix.split("::")
            if len(parts) >= 3 and parts[-1].startswith("Chapter"):
                deck_prefix = f"{existing_book_prefix}::{parts[-1]}"
    else:
        deck_prefix = default_deck_prefix
        ledger = {
            "book": book_name,
            "book_slug": book_slug,
            "chapter": int(ch_num),
            "deck_prefix": deck_prefix,
            "last_synced": None,
            "cards": [],
        }

    ledger["book"] = book_name
    ledger["book_slug"] = book_slug
    ledger["chapter"] = int(ch_num)
    ledger["deck_prefix"] = deck_prefix

    existing_cards: list[dict[str, Any]] = ledger.get("cards", [])

    scratch_files = sorted(cache_ch_dir.glob("cards_*.json")) if cache_ch_dir.exists() else []
    if not scratch_files:
        for card in existing_cards:
            if card.get("status") == "orphaned":
                continue
            raw_front = card.get("raw_front") or card.get("front", "")
            raw_back = card.get("raw_back") or card.get("back", "")
            anki_front, media_f = convert_markdown_and_math_to_anki(raw_front, book_slug, ch_num)
            anki_back, media_b = convert_markdown_and_math_to_anki(raw_back, book_slug, ch_num)
            all_media = list(dict.fromkeys((card.get("media") or []) + media_f + media_b))
            model_type = normalize_model_type(card.get("model_name", "Basic"), anki_front)
            card["model_name"] = model_type
            card["anki_front"] = anki_front
            card["anki_back"] = anki_back
            card["media"] = [Path(m).name for m in all_media]
            card["status"] = card.get("status", "active")
        ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
        return ledger_path, ledger

    by_section: dict[str, list[dict[str, Any]]] = {}
    for c in existing_cards:
        sec = str(c.get("section", ""))
        by_section.setdefault(sec, []).append(c)

    updated_sections: set[str] = set()
    new_section_cards: dict[str, list[dict[str, Any]]] = {}

    for sfile in scratch_files:
        try:
            sdata = json.loads(sfile.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Warning: Failed to parse {sfile}: {exc}", file=sys.stderr)
            continue

        sec_num = str(sdata.get("section", "")).strip()
        if not sec_num:
            m_sec = re.search(r"cards_(\d+)_(\d+)", sfile.stem)
            sec_num = f"{m_sec.group(1)}.{m_sec.group(2)}" if m_sec else f"{ch_num}.1"

        if section_filter and sec_num != section_filter:
            continue

        updated_sections.add(sec_num)
        sec_title = sanitize_filename(sdata.get("section_title") or sdata.get("subdeck") or f"Section {sec_num}")
        if not sec_title.startswith(sec_num):
            subdeck_name = f"{sec_num} {sec_title}"
        else:
            subdeck_name = sec_title

        old_sec_cards = by_section.get(sec_num, [])
        old_by_id = {c["id"]: c for c in old_sec_cards if "id" in c}
        old_by_front = {
            (c.get("raw_front") or c.get("front", "")).strip().lower(): c
            for c in old_sec_cards
        }
        matched_old_ids: set[str] = set()
        merged_for_sec: list[dict[str, Any]] = []

        raw_cards_list = sdata.get("cards", [])
        for idx, rc in enumerate(raw_cards_list, start=1):
            default_id = f"ch{int(ch_num):02d}_s{sec_num.replace('.', '_')}_c{idx:02d}"
            cid = rc.get("id") or default_id
            raw_front = (rc.get("raw_front") or rc.get("front") or "").strip()
            raw_back = (rc.get("raw_back") or rc.get("back") or "").strip()
            if not raw_front:
                continue

            matched_old = old_by_id.get(cid)
            if not matched_old and raw_front.lower() in old_by_front:
                candidate = old_by_front[raw_front.lower()]
                if candidate.get("id") not in matched_old_ids:
                    matched_old = candidate
                    cid = candidate.get("id", cid)

            if matched_old and matched_old.get("id"):
                matched_old_ids.add(matched_old["id"])

            anki_front, media_f = convert_markdown_and_math_to_anki(raw_front, book_slug, ch_num)
            anki_back, media_b = convert_markdown_and_math_to_anki(raw_back, book_slug, ch_num)

            explicit_media = [Path(m).name for m in (rc.get("media") or [])]
            all_media = list(dict.fromkeys(explicit_media + media_f + media_b))

            model_type = normalize_model_type(
                rc.get("model") or rc.get("model_name") or "Basic", anki_front
            )

            base_tags = [
                book_slug[:24],
                f"chapter-{int(ch_num):02d}",
                f"sec-{sec_num}",
            ]
            custom_tags = [
                re.sub(r"\s+", "-", t.strip().lower())
                for t in (rc.get("tags") or [])
                if t.strip() and t.strip() != ORPHAN_TAG
            ]
            tags = list(dict.fromkeys(base_tags + custom_tags))

            entry: dict[str, Any] = {
                "id": cid,
                "section": sec_num,
                "subdeck": subdeck_name,
                "model_name": model_type,
                "raw_front": raw_front,
                "raw_back": raw_back,
                "anki_front": anki_front,
                "anki_back": anki_back,
                "tags": tags,
                "media": all_media,
                "status": "active",
                "content_hash": matched_old.get("content_hash") if matched_old else None,
                "anki_note_id": matched_old.get("anki_note_id") if matched_old else None,
                "anki_actual_model": matched_old.get("anki_actual_model") if matched_old else None,
                "synced": matched_old.get("synced", False) if matched_old else False,
            }
            merged_for_sec.append(entry)

        for old_c in old_sec_cards:
            old_id = old_c.get("id")
            if old_id not in matched_old_ids:
                if old_c.get("anki_note_id") is not None:
                    was_already_orphaned = old_c.get("status") == "orphaned"
                    old_c["status"] = "orphaned"
                    if not was_already_orphaned:
                        old_c["synced"] = False
                    merged_for_sec.append(old_c)

        new_section_cards[sec_num] = merged_for_sec

    all_sec_keys = sorted(
        set(by_section.keys()) | set(new_section_cards.keys()),
        key=lambda s: [int(x) if x.isdigit() else 999 for x in s.split(".")],
    )
    final_cards: list[dict[str, Any]] = []
    for sec_key in all_sec_keys:
        if sec_key in updated_sections:
            final_cards.extend(new_section_cards[sec_key])
        else:
            final_cards.extend(by_section.get(sec_key, []))

    ledger["cards"] = final_cards
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    return ledger_path, ledger


def find_asset_file(
    workspace_root: Path, cfg: dict[str, Any], book_name: str, ch_num: str, filename: str
) -> Path | None:
    """Locate a cropped figure PNG in the chapter's vault assets directory."""
    vault_root = (workspace_root / cfg["vault_dir"]).resolve()
    clean_book = sanitize_filename(book_name)
    book_vault_dir = vault_root / clean_book
    if book_vault_dir.exists():
        for p in book_vault_dir.rglob(filename):
            if p.is_file():
                return p
    for p in vault_root.rglob(filename):
        if p.is_file():
            return p
    return None


def propagate_parent_deck_config(
    url: str, deck_root: str, deck_prefix: str, target_decks: list[str]
) -> dict[str, Any] | None:
    """
    Ensure newly created or synced subdecks automatically inherit the Anki Deck Options preset
    configured on the book deck (`Textbooks::<Book>`) or root deck (`Textbooks`).
    """
    try:
        anki_request(url, "createDeck", deck=deck_root)
        parts = deck_prefix.split("::")
        book_deck = "::".join(parts[:2]) if len(parts) >= 2 else deck_root
        anki_request(url, "createDeck", deck=book_deck)

        root_cfg = anki_request(url, "getDeckConfig", deck=deck_root) or {}
        book_cfg = anki_request(url, "getDeckConfig", deck=book_deck) or {}

        # Prefer a custom preset on the Book deck if it differs from Default (id=1);
        # otherwise inherit from the Root deck (`Textbooks`).
        if book_cfg.get("id") and int(book_cfg["id"]) != 1:
            chosen_cfg = book_cfg
            source_deck = book_deck
        else:
            chosen_cfg = root_cfg
            source_deck = deck_root

        config_id = chosen_cfg.get("id")
        if config_id is None:
            return None

        all_targets = list(dict.fromkeys([book_deck, deck_prefix] + target_decks))
        anki_request(url, "setDeckConfigId", decks=all_targets, configId=int(config_id))
        return {
            "source_deck": source_deck,
            "preset_id": int(config_id),
            "preset_name": chosen_cfg.get("name", "Default"),
            "applied_to_decks": len(all_targets),
        }
    except Exception:
        return None


def sync_chapter_to_anki(
    workspace_root: Path,
    cfg: dict[str, Any],
    book_name: str,
    ch_num: str,
    section_filter: str | None = None,
    force: bool = False,
    prune: bool = False,
) -> dict[str, Any]:
    """
    Aggregate section flashcards into `decks/<book_slug>/ch_<XX>_cards.json` and
    synchronize non-destructively with Anki via AnkiConnect.
    """
    ledger_path, ledger = aggregate_chapter_cards(
        workspace_root, cfg, book_name, ch_num, section_filter=section_filter
    )
    cards: list[dict[str, Any]] = ledger.get("cards", [])
    book_slug = ledger["book_slug"]
    deck_prefix = ledger["deck_prefix"]
    url = cfg.get("anki_connect_url", "http://127.0.0.1:8765")

    active_cards = [c for c in cards if c.get("status", "active") == "active"]
    orphaned_cards = [c for c in cards if c.get("status") == "orphaned"]

    if not check_anki_connection(url):
        for c in active_cards:
            new_h = compute_card_hash(
                c["subdeck"],
                c["model_name"],
                c.get("anki_front", ""),
                c.get("anki_back", ""),
                c.get("tags", []),
            )
            if c.get("content_hash") != new_h or c.get("anki_note_id") is None:
                c["synced"] = False
        ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
        pending = sum(1 for c in cards if not c.get("synced", False))
        return {
            "anki_connected": False,
            "ledger_path": str(ledger_path.resolve()),
            "active_cards": len(active_cards),
            "orphaned_cards": len(orphaned_cards),
            "pending_sync": pending,
            "message": (
                "Anki is offline or AnkiConnect (127.0.0.1:8765) is not reachable. "
                f"{len(active_cards)} active flashcards are safely staged in '{ledger_path.name}'. "
                "Open Anki and run `python book_tool.py sync-anki` anytime to push them."
            ),
        }

    models_map = resolve_anki_models(url, cfg)

    # 1. Upload referenced media assets to Anki's collection.media
    uploaded_media: list[str] = []
    seen_media: set[str] = set()
    for c in active_cards:
        if section_filter and str(c.get("section")) != section_filter:
            continue
        for raw_m in c.get("media", []):
            base_m = Path(raw_m).name
            if base_m in seen_media:
                continue
            seen_media.add(base_m)
            asset_path = find_asset_file(workspace_root, cfg, book_name, ch_num, base_m)
            if asset_path and asset_path.exists():
                anki_fname = make_anki_media_filename(book_slug, ch_num, base_m)
                b64_data = base64.b64encode(asset_path.read_bytes()).decode("ascii")
                anki_request(
                    url,
                    "storeMediaFile",
                    filename=anki_fname,
                    data=b64_data,
                )
                uploaded_media.append(anki_fname)

    # 2. Query existing notesInfo for all known anki_note_ids
    known_ids = [
        int(c["anki_note_id"])
        for c in cards
        if c.get("anki_note_id") is not None
    ]
    existing_notes_by_id: dict[int, dict[str, Any]] = {}
    if known_ids:
        notes_info = anki_request(url, "notesInfo", notes=known_ids) or []
        for ni in notes_info:
            if ni and ni.get("noteId"):
                existing_notes_by_id[int(ni["noteId"])] = ni

    stats = {
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "suspended_orphans": 0,
        "pruned_orphans": 0,
        "model_migrations": 0,
    }

    anki_request(url, "createDeck", deck=deck_prefix)
    synced_subdecks: list[str] = []

    kept_cards: list[dict[str, Any]] = []
    for c in cards:
        if section_filter and str(c.get("section")) != section_filter:
            kept_cards.append(c)
            continue

        status = c.get("status", "active")
        note_id = int(c["anki_note_id"]) if c.get("anki_note_id") is not None else None
        existing_info = existing_notes_by_id.get(note_id) if note_id else None

        # Handle Orphaned Cards
        if status == "orphaned":
            if existing_info:
                if prune:
                    anki_request(url, "deleteNotes", notes=[note_id])
                    stats["pruned_orphans"] += 1
                    continue
                elif not c.get("synced", False) or force:
                    card_ids = existing_info.get("cards", [])
                    if card_ids:
                        anki_request(url, "suspend", cards=card_ids)
                    anki_request(url, "addTags", notes=[note_id], tags=ORPHAN_TAG)
                    c["synced"] = True
                    stats["suspended_orphans"] += 1
            else:
                if prune:
                    continue
                c["synced"] = True
            kept_cards.append(c)
            continue

        # Handle Active Cards
        subdeck = c.get("subdeck") or f"Section {c.get('section', '1.1')}"
        full_deck_name = f"{deck_prefix}::{subdeck}"
        if full_deck_name not in synced_subdecks:
            anki_request(url, "createDeck", deck=full_deck_name)
            synced_subdecks.append(full_deck_name)

        anki_front = c.get("anki_front") or ""
        anki_back = c.get("anki_back") or ""
        logical_model = normalize_model_type(c.get("model_name", "Basic"), anki_front)
        c["model_name"] = logical_model
        model_spec = models_map[logical_model]
        actual_model_name = model_spec["model_name"]
        front_field = model_spec["front_field"]
        back_field = model_spec["back_field"]

        tags = [t for t in c.get("tags", []) if t != ORPHAN_TAG]
        c["tags"] = tags
        new_hash = compute_card_hash(subdeck, logical_model, anki_front, anki_back, tags)

        # Check if note model changed
        if existing_info is not None and existing_info.get("modelName") != actual_model_name:
            old_card_ids = existing_info.get("cards", [])
            if old_card_ids:
                anki_request(url, "suspend", cards=old_card_ids)
            anki_request(url, "addTags", notes=[note_id], tags=ORPHAN_TAG)
            c.setdefault("previous_note_ids", []).append(note_id)
            existing_info = None
            note_id = None
            stats["model_migrations"] += 1

        # If an existing Cloze note previously had >1 sibling cards (e.g. from c2) and now only has c1,
        # check if it has 0 reviews; if unreviewed, replace it cleanly so Anki doesn't keep an empty Carta 2!
        if existing_info is not None and len(existing_info.get("cards", [])) > 1 and "{{c2::" not in anki_front:
            c_infos = anki_request(url, "cardsInfo", cards=existing_info["cards"]) or []
            total_reps = sum(int(ci.get("reps", 0)) for ci in c_infos)
            if total_reps == 0:
                anki_request(url, "deleteNotes", notes=[note_id])
                existing_info = None
                note_id = None
            else:
                # Suspend the extra sibling card(s) with ord > 0 so reviews on ord 0 are preserved
                extra_cards = [int(ci["cardId"]) for ci in c_infos if int(ci.get("ord", 0)) > 0]
                if extra_cards:
                    anki_request(url, "suspend", cards=extra_cards)

        if existing_info is None:
            note_payload = {
                "deckName": full_deck_name,
                "modelName": actual_model_name,
                "fields": {
                    front_field: anki_front,
                    back_field: anki_back,
                },
                "options": {
                    "allowDuplicate": True,
                },
                "tags": tags,
            }
            new_note_id = anki_request(url, "addNote", note=note_payload)
            c["anki_note_id"] = int(new_note_id)
            c["anki_actual_model"] = actual_model_name
            c["content_hash"] = new_hash
            c["synced"] = True
            stats["added"] += 1
        else:
            if c.get("content_hash") != new_hash or not c.get("synced", False) or force:
                anki_request(
                    url,
                    "updateNoteFields",
                    note={
                        "id": note_id,
                        "fields": {
                            front_field: anki_front,
                            back_field: anki_back,
                        },
                    },
                )
                card_ids = existing_info.get("cards", [])
                if card_ids:
                    anki_request(url, "changeDeck", cards=card_ids, deck=full_deck_name)
                    if ORPHAN_TAG in (existing_info.get("tags") or []):
                        anki_request(url, "unsuspend", cards=card_ids)
                        anki_request(url, "removeTags", notes=[note_id], tags=ORPHAN_TAG)

                if tags:
                    anki_request(url, "addTags", notes=[note_id], tags=" ".join(tags))

                c["anki_actual_model"] = actual_model_name
                c["content_hash"] = new_hash
                c["synced"] = True
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

        kept_cards.append(c)

    deck_root = cfg.get("anki_deck_root", "Textbooks")
    preset_info = propagate_parent_deck_config(url, deck_root, deck_prefix, synced_subdecks)

    ledger["cards"] = kept_cards
    ledger["last_synced"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "anki_connected": True,
        "ledger_path": str(ledger_path.resolve()),
        "deck_prefix": deck_prefix,
        "deck_preset": preset_info,
        "stats": stats,
        "media_uploaded": uploaded_media,
        "total_active_cards": sum(1 for c in kept_cards if c.get("status", "active") == "active"),
        "total_orphaned_cards": sum(1 for c in kept_cards if c.get("status") == "orphaned"),
    }


# ============================================================================
# CLI Commands
# ============================================================================

def cmd_status(workspace_root: Path, cfg: dict[str, Any]) -> None:
    import fitz

    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = read_target_chapter(workspace_root / cfg["chapter_file"])
    book_name = pdf_path.stem
    book_slug = slugify(book_name)
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    anki_url = cfg.get("anki_connect_url", "http://127.0.0.1:8765")
    anki_online = check_anki_connection(anki_url)
    ledger_path = get_deck_ledger_path(workspace_root, cfg, book_slug, ch_num)

    info = {
        "active_pdf": str(pdf_path.resolve()),
        "book_name": book_name,
        "total_pdf_pages": len(doc),
        "has_bookmarks": len(toc) > 0,
        "bookmark_count": len(toc),
        "target_chapter": ch_num,
        "anki_connect_url": anki_url,
        "anki_connected": anki_online,
        "chapter_deck_ledger": str(ledger_path.resolve()),
        "chapter_deck_exists": ledger_path.exists(),
    }
    print(json.dumps(info, indent=2))


def cmd_prepare(workspace_root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> None:
    import fitz

    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = str(args.chapter) if args.chapter else read_target_chapter(workspace_root / cfg["chapter_file"])
    book_name = pdf_path.stem
    book_slug = slugify(book_name)

    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()

    parsed = parse_toc_for_chapter(toc, ch_num, len(doc), cfg["skip_section_keywords"])
    discovery_method = "pdf_bookmarks"
    if not parsed or not parsed.get("sections"):
        fallback = scan_text_for_chapter_sections(doc, ch_num, cfg["skip_section_keywords"])
        if not parsed:
            parsed = fallback
            discovery_method = "text_heuristic_scan"
        elif not parsed.get("sections") and fallback.get("sections"):
            parsed["sections"] = fallback["sections"]
            discovery_method = "hybrid_bookmarks_and_text"

    if args.pages:
        m = re.match(r"^(\d+)-(\d+)$", args.pages.strip())
        if not m:
            raise ValueError("--pages must be in START-END format (1-based PDF page numbers, e.g., 12-28)")
        parsed["start_pdf_page"] = int(m.group(1))
        parsed["end_pdf_page"] = int(m.group(2))
        discovery_method = "explicit_page_range"

    if args.chapter_title:
        parsed["chapter_title"] = args.chapter_title

    cache_ch_dir = (workspace_root / cfg["cache_dir"] / book_slug / f"ch_{int(ch_num):02d}").resolve()
    pages_dir = cache_ch_dir / "pages"

    rendered_pages = render_pdf_pages(
        doc,
        parsed["start_pdf_page"],
        parsed["end_pdf_page"],
        pages_dir,
        int(cfg["render_dpi"]),
    )

    ch_vault_dir = get_vault_chapter_dir(
        workspace_root, cfg, book_name, ch_num, parsed["chapter_title"]
    )
    ch_vault_dir.mkdir(parents=True, exist_ok=True)
    (ch_vault_dir / "assets").mkdir(parents=True, exist_ok=True)

    ledger_path = get_deck_ledger_path(workspace_root, cfg, book_slug, ch_num)
    assets_manifest_path = cache_ch_dir / "assets_manifest.json"

    for sec in parsed["sections"]:
        sec_num = sec["section_number"]
        clean_title = sanitize_filename(sec["title"])
        md_filename = f"{sec_num} {clean_title}.md"
        sec["note_filename"] = md_filename
        sec["note_path"] = str((ch_vault_dir / md_filename).resolve())
        sec["cards_scratch_path"] = str(
            (cache_ch_dir / f"cards_{sec_num.replace('.', '_')}.json").resolve()
        )
        s_start = int(sec.get("start_pdf_page", parsed["start_pdf_page"]))
        s_end = int(sec.get("end_pdf_page", s_start))
        sec["page_pngs"] = [
            str((pages_dir / f"pdf_page_{p:04d}.png").resolve())
            for p in range(s_start, s_end + 1)
        ]

    manifest = {
        "book_name": book_name,
        "book_slug": book_slug,
        "pdf_path": str(pdf_path.resolve()),
        "total_pdf_pages": len(doc),
        "chapter_number": ch_num,
        "chapter_title": parsed["chapter_title"],
        "discovery_method": discovery_method,
        "start_pdf_page": parsed["start_pdf_page"],
        "end_pdf_page": parsed["end_pdf_page"],
        "vault_chapter_dir": str(ch_vault_dir.resolve()),
        "assets_dir": str((ch_vault_dir / "assets").resolve()),
        "assets_manifest_path": str(assets_manifest_path.resolve()),
        "deck_ledger_path": str(ledger_path.resolve()),
        "cache_chapter_dir": str(cache_ch_dir.resolve()),
        "cache_pages_dir": str(pages_dir.resolve()),
        "sections": parsed["sections"],
        "active_sections_to_synthesize": [
            s for s in parsed["sections"] if not s.get("skipped", False)
        ],
        "skipped_sections": [
            s for s in parsed["sections"] if s.get("skipped", False)
        ],
        "rendered_pages": rendered_pages,
    }

    manifest_path = cache_ch_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest saved to: {manifest_path}")
    print(json.dumps(manifest, indent=2))


def cmd_crop(workspace_root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> None:
    from PIL import Image

    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = str(args.chapter) if args.chapter else read_target_chapter(workspace_root / cfg["chapter_file"])
    book_name = pdf_path.stem
    book_slug = slugify(book_name)

    cache_ch_dir = (workspace_root / cfg["cache_dir"] / book_slug / f"ch_{int(ch_num):02d}").resolve()
    manifest_path = cache_ch_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found at {manifest_path}. Run `python book_tool.py prepare` first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    page_num = int(args.page)
    page_img_path = Path(manifest["cache_pages_dir"]) / f"pdf_page_{page_num:04d}.png"
    if not page_img_path.exists():
        import fitz

        doc = fitz.open(str(pdf_path))
        render_pdf_pages(doc, page_num, page_num, Path(manifest["cache_pages_dir"]), int(cfg["render_dpi"]))

    img = Image.open(page_img_path)
    width, height = img.size

    coords = [float(x.strip()) for x in args.bbox.split(",")]
    if len(coords) != 4:
        raise ValueError("--bbox must have 4 comma-separated numbers: ymin,xmin,ymax,xmax (0-1000 normalized)")

    ymin, xmin, ymax, xmax = coords
    if not args.pixels:
        ymin = (ymin / 1000.0) * height
        ymax = (ymax / 1000.0) * height
        xmin = (xmin / 1000.0) * width
        xmax = (xmax / 1000.0) * width

    pad_pct = float(cfg.get("crop_padding_pct", 0.05))
    box_w = max(1.0, xmax - xmin)
    box_h = max(1.0, ymax - ymin)
    pad_x = box_w * pad_pct
    pad_y = box_h * pad_pct

    left = max(0, int(xmin - pad_x))
    top = max(0, int(ymin - pad_y))
    right = min(width, int(xmax + pad_x))
    bottom = min(height, int(ymax + pad_y))

    cropped = img.crop((left, top, right, bottom))

    out_name = args.out
    if not out_name.lower().endswith(".png"):
        out_name += ".png"
    out_path = Path(manifest["assets_dir"]) / sanitize_filename(Path(out_name).stem)
    out_path = out_path.with_suffix(".png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(str(out_path))

    sec_match = re.match(r"^fig_(\d+)_(\d+)_", out_path.name)
    inferred_section = f"{sec_match.group(1)}.{sec_match.group(2)}" if sec_match else None

    assets_manifest_path = cache_ch_dir / "assets_manifest.json"
    assets_data: dict[str, Any] = {"assets": []}
    if assets_manifest_path.exists():
        try:
            assets_data = json.loads(assets_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            assets_data = {"assets": []}

    entry = {
        "filename": out_path.name,
        "section": inferred_section,
        "obsidian_embed": f"![[assets/{out_path.name}]]",
        "source_pdf_page": page_num,
        "bbox": args.bbox,
        "pixel_box": [left, top, right, bottom],
        "cropped_image_path": str(out_path.resolve()),
    }
    existing_list = [
        a for a in assets_data.get("assets", []) if a.get("filename") != out_path.name
    ]
    existing_list.append(entry)
    assets_data["assets"] = existing_list
    assets_manifest_path.write_text(json.dumps(assets_data, indent=2), encoding="utf-8")

    result = {
        "cropped_image_path": str(out_path.resolve()),
        "obsidian_embed": f"![[assets/{out_path.name}]]",
        "section": inferred_section,
        "source_pdf_page": page_num,
        "pixel_box": [left, top, right, bottom],
        "assets_manifest_path": str(assets_manifest_path.resolve()),
    }
    print(json.dumps(result, indent=2))


def sanitize_mathjax(markdown_text: str) -> str:
    code_tokens: list[str] = []

    def save_code(m: re.Match[str]) -> str:
        code_tokens.append(m.group(0))
        return f"\x00CODE{len(code_tokens)-1}\x00"

    text = re.sub(r"```[\s\S]*?```", save_code, markdown_text)
    text = re.sub(r"`[^`\n]+?`", save_code, text)

    def format_display_math(m: re.Match[str]) -> str:
        bq_start = m.group(1) or ""
        inner = m.group(2)
        bq_end = m.group(3) or ""

        has_bq = (
            bq_start.strip().startswith(">")
            or bq_end.strip().startswith(">")
            or any(line.strip().startswith(">") for line in inner.split("\n"))
        )
        if has_bq:
            prefix = bq_start if bq_start.strip().startswith(">") else (bq_end if bq_end.strip().startswith(">") else "> ")
            if not prefix.endswith(" "):
                prefix += " "
            clean_lines = [re.sub(r"^[ \t]*>[ \t]*", "", l) for l in inner.split("\n")]
            clean_inner = "\n".join(clean_lines).strip()
            lines = [f"{prefix}{l}" if l.strip() else prefix.rstrip() for l in clean_inner.split("\n")]
            formatted = "\n".join(lines)
            return f"{prefix.rstrip()}\n{prefix}$$\n{formatted}\n{prefix}$$\n{prefix.rstrip()}"
        else:
            clean_inner = inner.strip()
            return f"\n\n$$\n{clean_inner}\n$$\n\n"

    text = re.sub(r"(?m)^([ \t]*(?:>[ \t]*)+)?\$\$([\s\S]*?)^([ \t]*(?:>[ \t]*)+)?\$\$", format_display_math, text)

    # Ensure any callouts / blockquotes never contain unquoted bare empty lines
    lines = text.split("\n")
    fixed_lines: list[str] = []
    in_callout = False
    for idx, l in enumerate(lines):
        if re.match(r"^[ \t]*>[ \t]*\[!", l):
            in_callout = True
            fixed_lines.append(l)
        elif in_callout:
            if l.strip() == "":
                # Peek ahead to check if this is within the same callout
                next_l = ""
                for k in range(idx + 1, len(lines)):
                    if lines[k].strip() != "":
                        next_l = lines[k]
                        break
                if next_l.strip().startswith(">"):
                    if re.match(r"^[ \t]*>[ \t]*\[!", next_l):
                        in_callout = False
                        fixed_lines.append(l)
                    else:
                        fixed_lines.append(">")
                else:
                    in_callout = False
                    fixed_lines.append(l)
            elif not l.strip().startswith(">"):
                in_callout = False
                fixed_lines.append(l)
            else:
                fixed_lines.append(l)
        else:
            fixed_lines.append(l)
    text = "\n".join(fixed_lines)
    text = re.sub(r"(?m)^>[ \t]*\n(?:>[ \t]*\n)+", ">\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    display_tokens: list[str] = []

    def save_display(m: re.Match[str]) -> str:
        display_tokens.append(m.group(0))
        return f"\x00DISPLAY{len(display_tokens)-1}\x00"

    text = re.sub(r"(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$", save_display, text)

    inline_re = re.compile(r"(?<![\$\\])\$(?!\$)([^\$\n]+?)(?<![\$\\])\$(?!\$)")

    lines = text.split("\n")
    processed_lines: list[str] = []

    for line in lines:
        matches = list(inline_re.finditer(line))
        if not matches:
            processed_lines.append(line)
            continue

        new_line: list[str] = []
        last_idx = 0

        for m in matches:
            start, end = m.span()
            inner = m.group(1).strip()
            math_str = f"${inner}$"

            prefix = line[last_idx:start]
            if prefix:
                if re.search(r"(\w|[\)\],;:]|[^\s\*\_](\*\*|\*|__|_)|[^\s\"'](\"|')|\x00CODE\d+\x00)$", prefix):
                    prefix += " "
                elif prefix.endswith("|"):
                    prefix += " "

            new_line.append(prefix)

            next_chars = line[end:]
            suffix = ""
            if next_chars:
                next_char = next_chars[0]
                if re.match(r"[a-zA-Z0-9\(]", next_char):
                    suffix = " "
                elif next_char == "|":
                    suffix = " "
                elif re.match(r"[\"']\w", next_chars):
                    suffix = " "
                elif next_chars.startswith("\x00CODE"):
                    suffix = " "
                elif re.match(r"(\*\*|\*|__|_)\w", next_chars):
                    suffix = " "

            new_line.append(math_str + suffix)
            last_idx = end

        new_line.append(line[last_idx:])
        processed_lines.append("".join(new_line))

    result = "\n".join(processed_lines)

    for i, dt in enumerate(display_tokens):
        result = result.replace(f"\x00DISPLAY{i}\x00", dt)

    for i, ct in enumerate(code_tokens):
        result = result.replace(f"\x00CODE{i}\x00", ct)

    return result


def extract_preserved_user_notes(existing_file: Path) -> str:
    if not existing_file.exists():
        return ""
    content = existing_file.read_text(encoding="utf-8")
    if USER_NOTES_MARKER in content:
        _, after = content.split(USER_NOTES_MARKER, 1)
        return after.strip()
    return ""


def cmd_finalize(workspace_root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> None:
    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = str(args.chapter) if args.chapter else read_target_chapter(workspace_root / cfg["chapter_file"])
    book_name = pdf_path.stem
    book_slug = slugify(book_name)

    cache_ch_dir = (workspace_root / cfg["cache_dir"] / book_slug / f"ch_{int(ch_num):02d}").resolve()
    manifest_path = cache_ch_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found at {manifest_path}. Run `python book_tool.py prepare` first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ch_vault_dir = Path(manifest["vault_chapter_dir"])
    ch_title = manifest["chapter_title"]
    moc_name = f"00 - Chapter {int(ch_num):02d} MOC"
    moc_path = ch_vault_dir / f"{moc_name}.md"

    sec_files = sorted(
        [
            p
            for p in ch_vault_dir.glob("*.md")
            if p.name != moc_path.name and re.match(rf"^0*{re.escape(ch_num)}\.\d+\b", p.name)
        ],
        key=lambda p: [
            int(x)
            for x in re.match(r"^(\d+\.\d+)", p.name).group(1).split(".")
        ],
    )

    updated_notes: list[str] = []
    moc_entries: list[str] = []

    for idx, note_path in enumerate(sec_files):
        raw_text = note_path.read_text(encoding="utf-8")
        user_notes = ""
        if USER_NOTES_MARKER in raw_text:
            body_part, user_notes = raw_text.split(USER_NOTES_MARKER, 1)
        else:
            body_part = raw_text

        body_part = sanitize_mathjax(body_part.strip())

        prev_link = f"← [[{sec_files[idx - 1].stem}]]" if idx > 0 else "← *Start of Chapter*"
        next_link = f"[[{sec_files[idx + 1].stem}]] →" if idx + 1 < len(sec_files) else "*End of Chapter* →"
        nav_line = f"> **Navigation**: {prev_link} | **[[{moc_name}|Chapter {ch_num} MOC]]** | {next_link}"

        nav_pattern = re.compile(r"^> \*\*Navigation\*\*:.*$", re.MULTILINE)
        if nav_pattern.search(body_part):
            body_part = nav_pattern.sub(nav_line, body_part)
        else:
            if body_part.startswith("---"):
                end_fm = body_part.find("---", 3)
                if end_fm != -1:
                    insert_pos = end_fm + 3
                    body_part = (
                        body_part[:insert_pos]
                        + f"\n\n{nav_line}\n"
                        + body_part[insert_pos:]
                    )
            else:
                body_part = f"{nav_line}\n\n{body_part}"

        body_part = re.sub(r"(\n\s*---\s*)*$", "", body_part.rstrip())
        final_content = f"{body_part.rstrip()}\n\n---\n{USER_NOTES_MARKER}\n"
        if user_notes.strip():
            final_content += f"{user_notes.strip()}\n"

        note_path.write_text(final_content, encoding="utf-8")
        updated_notes.append(note_path.name)
        moc_entries.append(f"- [[{note_path.stem}]]")

    skipped_list = manifest.get("skipped_sections", [])
    skipped_md = (
        "\n".join(f"- *{s['section_number']} {s['title']} (Skipped — Non-Primer Section)*" for s in skipped_list)
        if skipped_list
        else "- *None*"
    )

    moc_content = f"""---
book: "{book_name}"
chapter: {ch_num}
title: "{ch_title}"
type: moc
tags:
  - textbook-primer
  - chapter-{ch_num}
  - moc
---

# Chapter {ch_num}: {ch_title} — Map of Content

> [!abstract] Pre-Reading Primer Overview
> This Map of Content links the section-by-section pre-reading primers for **Chapter {ch_num} ({ch_title})** of *{book_name}*. Read each primer to build physical/mathematical intuition and master the notation before reading the corresponding section in the textbook.

## Section Primers
{chr(10).join(moc_entries) if moc_entries else "- *No section notes generated yet.*"}

## Ignored / Non-Content Sections
{skipped_md}

---
{USER_NOTES_MARKER}
"""
    existing_moc_user_notes = extract_preserved_user_notes(moc_path)
    if existing_moc_user_notes:
        moc_content += f"{existing_moc_user_notes}\n"

    moc_path.write_text(moc_content, encoding="utf-8")

    if getattr(args, "notes_only", False):
        anki_sync_report: dict[str, Any] = {
            "skipped": True,
            "reason": "--notes-only flag passed; Anki flashcard sync bypassed.",
        }
    else:
        anki_sync_report = sync_chapter_to_anki(
            workspace_root, cfg, book_name, ch_num
        )

    summary = {
        "moc_path": str(moc_path.resolve()),
        "finalized_section_notes": updated_notes,
        "vault_chapter_dir": str(ch_vault_dir.resolve()),
        "anki_sync": anki_sync_report,
    }
    print(json.dumps(summary, indent=2))


def cmd_sync_anki(workspace_root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> None:
    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = str(args.chapter) if args.chapter else read_target_chapter(workspace_root / cfg["chapter_file"])
    book_name = pdf_path.stem

    report = sync_chapter_to_anki(
        workspace_root,
        cfg,
        book_name,
        ch_num,
        section_filter=args.section,
        force=args.force,
        prune=args.prune,
    )
    print(json.dumps(report, indent=2))


def cmd_refresh_cards(workspace_root: Path, cfg: dict[str, Any], args: argparse.Namespace) -> None:
    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = str(args.chapter) if args.chapter else read_target_chapter(workspace_root / cfg["chapter_file"])
    book_name = pdf_path.stem
    book_slug = slugify(book_name)

    cache_ch_dir = (workspace_root / cfg["cache_dir"] / book_slug / f"ch_{int(ch_num):02d}").resolve()
    cache_ch_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = cache_ch_dir / "pages"
    manifest_path = cache_ch_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    vault_root = (workspace_root / cfg["vault_dir"]).resolve()
    clean_book = sanitize_filename(book_name)
    book_vault_dir = vault_root / clean_book

    ch_dirs = (
        sorted(book_vault_dir.glob(f"Chapter {int(ch_num):02d}*"))
        if book_vault_dir.exists()
        else []
    )
    if ch_dirs:
        ch_vault_dir = ch_dirs[0]
    elif manifest.get("vault_chapter_dir"):
        ch_vault_dir = Path(manifest["vault_chapter_dir"])
    else:
        raise FileNotFoundError(
            f"No existing synthesized vault folder or manifest found for Chapter {ch_num}. "
            "Run `python book_tool.py prepare` or `/synthesize` first."
        )

    assets_dir = ch_vault_dir / "assets"
    available_assets = sorted(p.name for p in assets_dir.glob("*.png")) if assets_dir.exists() else []

    assets_manifest_path = cache_ch_dir / "assets_manifest.json"
    manifest_assets_list: list[dict[str, Any]] = []
    if assets_manifest_path.exists():
        try:
            manifest_assets_list = json.loads(assets_manifest_path.read_text(encoding="utf-8")).get("assets", [])
        except Exception:
            manifest_assets_list = []

    ledger_path = get_deck_ledger_path(workspace_root, cfg, book_slug, ch_num)
    existing_cards: list[dict[str, Any]] = []
    if ledger_path.exists():
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        existing_cards = ledger_data.get("cards", [])

    manifest_sections_by_num: dict[str, dict[str, Any]] = {
        str(s.get("section_number")): s
        for s in manifest.get("sections", [])
        if s.get("section_number")
    }

    sec_files = sorted(
        [
            p
            for p in ch_vault_dir.glob("*.md")
            if re.match(rf"^0*{re.escape(ch_num)}\.\d+\b", p.name)
        ],
        key=lambda p: [
            int(x)
            for x in re.match(r"^(\d+\.\d+)", p.name).group(1).split(".")
        ],
    )

    sections_info: list[dict[str, Any]] = []
    for note_path in sec_files:
        m = re.match(r"^(\d+\.\d+)\s+(.*)$", note_path.stem)
        if not m:
            continue
        sec_num = m.group(1)
        sec_title = m.group(2)
        if args.section and sec_num != args.section:
            continue

        m_sec = manifest_sections_by_num.get(sec_num, {})
        s_start = m_sec.get("start_pdf_page")
        s_end = m_sec.get("end_pdf_page")
        page_pngs: list[str] = []
        if s_start is not None and s_end is not None:
            page_pngs = [
                str((pages_dir / f"pdf_page_{p:04d}.png").resolve())
                for p in range(int(s_start), int(s_end) + 1)
            ]

        sec_prefix = f"fig_{sec_num.replace('.', '_')}_"
        note_embeds: set[str] = set()
        if note_path.exists():
            note_text = note_path.read_text(encoding="utf-8")
            for emb_m in re.finditer(r"!\[\[(?:assets/)?([^\]|]+)\]\]", note_text):
                note_embeds.add(Path(emb_m.group(1).strip()).name)

        sec_assets = sorted(
            {
                a
                for a in available_assets
                if a.startswith(sec_prefix) or a in note_embeds
            }
            | {
                str(entry.get("filename"))
                for entry in manifest_assets_list
                if entry.get("filename")
                and (
                    entry.get("section") == sec_num
                    or (
                        s_start is not None
                        and s_end is not None
                        and entry.get("source_pdf_page") is not None
                        and int(s_start) <= int(entry["source_pdf_page"]) <= int(s_end)
                    )
                )
            }
        )

        sec_existing_cards = [
            {
                "id": c.get("id"),
                "model_name": c.get("model_name"),
                "raw_front": c.get("raw_front") or c.get("front"),
                "raw_back": c.get("raw_back") or c.get("back"),
                "tags": c.get("tags", []),
                "media": c.get("media", []),
                "status": c.get("status", "active"),
                "anki_note_id": c.get("anki_note_id"),
            }
            for c in existing_cards
            if str(c.get("section")) == sec_num
        ]

        sections_info.append(
            {
                "section_number": sec_num,
                "section_title": m_sec.get("title") or sec_title,
                "start_pdf_page": s_start,
                "end_pdf_page": s_end,
                "page_pngs": page_pngs,
                "section_assets": sec_assets,
                "note_path": str(note_path.resolve()),
                "cards_scratch_path": str(
                    (cache_ch_dir / f"cards_{sec_num.replace('.', '_')}.json").resolve()
                ),
                "existing_card_count": len(sec_existing_cards),
                "existing_cards": sec_existing_cards,
            }
        )

    info = {
        "book_name": book_name,
        "book_slug": book_slug,
        "chapter_number": ch_num,
        "vault_chapter_dir": str(ch_vault_dir.resolve()),
        "assets_dir": str(assets_dir.resolve()),
        "assets_manifest_path": str(assets_manifest_path.resolve()),
        "available_assets": available_assets,
        "deck_ledger_path": str(ledger_path.resolve()),
        "anki_connected": check_anki_connection(cfg.get("anki_connect_url", "http://127.0.0.1:8765")),
        "sections_to_refresh": sections_info,
    }
    print(json.dumps(info, indent=2))


def main() -> None:
    workspace_root = Path(__file__).resolve().parent
    cfg = load_config(workspace_root)

    parser = argparse.ArgumentParser(
        description="Local PDF, Obsidian Vault & AnkiConnect Toolkit for Book-Synthesizer"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Check active PDF, target chapter, and AnkiConnect status")

    p_prep = sub.add_parser("prepare", help="Slice target chapter, detect X.Y sections, and render 300-DPI PNGs")
    p_prep.add_argument("--chapter", type=str, default=None, help="Override chapter number from chapter.txt")
    p_prep.add_argument("--pages", type=str, default=None, help="Explicit 1-based PDF page range (e.g. 14-30)")
    p_prep.add_argument("--chapter-title", type=str, default=None, help="Explicit chapter title override")

    p_crop = sub.add_parser("crop", help="Crop a figure from a rendered 300-DPI PDF page with 5%% safety padding")
    p_crop.add_argument("--chapter", type=str, default=None, help="Override chapter number")
    p_crop.add_argument("--page", type=int, required=True, help="1-based PDF page number (matches pdf_page_XXXX.png)")
    p_crop.add_argument("--bbox", type=str, required=True, help="ymin,xmin,ymax,xmax (0-1000 normalized by default)")
    p_crop.add_argument("--out", type=str, required=True, help="Output figure filename (e.g. fig_1_3_arx.png)")
    p_crop.add_argument("--pixels", action="store_true", help="Interpret --bbox as raw pixel coordinates")

    p_fin = sub.add_parser("finalize", help="Sanitize MathJax, inject [[Prev]]/[[Next]] links, build MOC, & sync Anki")
    p_fin.add_argument("--chapter", type=str, default=None, help="Override chapter number")
    p_fin.add_argument(
        "--notes-only",
        action="store_true",
        help="Finalize Obsidian notes and MOC only, skipping Anki card aggregation and sync",
    )

    p_sync = sub.add_parser("sync-anki", help="Aggregate section flashcards into ./decks/ and sync via AnkiConnect")
    p_sync.add_argument("--chapter", type=str, default=None, help="Override chapter number")
    p_sync.add_argument("--section", type=str, default=None, help="Only aggregate/sync a specific section (e.g. 1.3)")
    p_sync.add_argument("--force", action="store_true", help="Force update all card fields in Anki even if hash matches")
    p_sync.add_argument("--prune", action="store_true", help="Permanently delete orphaned cards from Anki instead of suspending")

    p_ref = sub.add_parser(
        "refresh-cards",
        aliases=["cards"],
        help="Inspect 300-DPI section page PNGs, cropped assets & card ledger for standalone flashcard extraction/tuning",
    )
    p_ref.add_argument("--chapter", type=str, default=None, help="Override chapter number")
    p_ref.add_argument("--section", type=str, default=None, help="Target a single section (e.g. 1.3)")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(workspace_root, cfg)
    elif args.command == "prepare":
        cmd_prepare(workspace_root, cfg, args)
    elif args.command == "crop":
        cmd_crop(workspace_root, cfg, args)
    elif args.command == "finalize":
        cmd_finalize(workspace_root, cfg, args)
    elif args.command == "sync-anki":
        cmd_sync_anki(workspace_root, cfg, args)
    elif args.command in ("refresh-cards", "cards"):
        cmd_refresh_cards(workspace_root, cfg, args)


if __name__ == "__main__":
    main()
