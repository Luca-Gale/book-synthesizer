#!/usr/bin/env python3
"""
book_tool.py — Local PDF & Obsidian Vault Toolkit for Book-Synthesizer.

Designed to be orchestrated by Antigravity (zero external LLM API keys required).
Provides four deterministic commands:
  1. status   : Inspect active PDF in ./book/ and target chapter in ./chapter.txt
  2. prepare  : Extract ToC/sections for the target chapter and render 300-DPI page PNGs
  3. crop     : Crop a figure bounding box [ymin, xmin, ymax, xmax] with 5% padding into vault assets
  4. finalize : Sanitize MathJax, wire [[Prev]]/[[MOC]]/[[Next]] links, preserve user notes, & build Chapter MOC
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

USER_NOTES_MARKER = "<!-- USER NOTES BELOW THIS LINE -->"


def load_config(workspace_root: Path) -> dict[str, Any]:
    config_path = workspace_root / "config.json"
    default_cfg = {
        "book_dir": "./book",
        "chapter_file": "./chapter.txt",
        "vault_dir": "./vault",
        "cache_dir": "./.cache",
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
    # Replace em-dash, en-dash, colons, slashes with clean hyphen
    cleaned = re.sub(r"[—–:/\\|?*\"<>]", " - ", name)
    # Collapse multiple spaces/hyphens
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
    """
    Attempt to locate Chapter `target_ch` and its numbered sections `X.Y` from PDF bookmarks.
    `toc` items from PyMuPDF are `[level, title, page_1based]`.
    """
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
        # Avoid matching "1.1" as Chapter 1
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

    # Find where this chapter ends (next bookmark at <= ch_level)
    for j in range(ch_idx + 1, len(toc)):
        lvl, _title, page = toc[j]
        if lvl <= ch_level and page >= ch_start_page:
            ch_end_page = max(ch_start_page, page - 1)
            break

    # Collect X.Y sections inside this chapter
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

    # Calculate end_pdf_page for each section
    for idx, sec in enumerate(raw_sections):
        if idx + 1 < len(raw_sections):
            next_start = raw_sections[idx + 1]["start_pdf_page"]
            # Sections often share a boundary page where one ends and the next begins
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
    """
    Fallback when PDF bookmarks are missing or incomplete:
    Scans page text for lines matching `X.1 ...`, `X.2 ...` and Table of Contents entries.
    """
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
            # If it's in the body (no trailing page number, or after frontmatter)
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
    import fitz

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


def cmd_status(workspace_root: Path, cfg: dict[str, Any]) -> None:
    import fitz

    pdf_path = find_active_pdf(workspace_root / cfg["book_dir"])
    ch_num = read_target_chapter(workspace_root / cfg["chapter_file"])
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    info = {
        "active_pdf": str(pdf_path.resolve()),
        "book_name": pdf_path.stem,
        "total_pdf_pages": len(doc),
        "has_bookmarks": len(toc) > 0,
        "bookmark_count": len(toc),
        "target_chapter": ch_num,
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

    # Enrich each section with its target markdown file path
    for sec in parsed["sections"]:
        sec_num = sec["section_number"]
        clean_title = sanitize_filename(sec["title"])
        md_filename = f"{sec_num} {clean_title}.md"
        sec["note_filename"] = md_filename
        sec["note_path"] = str((ch_vault_dir / md_filename).resolve())

    manifest = {
        "book_name": book_name,
        "pdf_path": str(pdf_path.resolve()),
        "total_pdf_pages": len(doc),
        "chapter_number": ch_num,
        "chapter_title": parsed["chapter_title"],
        "discovery_method": discovery_method,
        "start_pdf_page": parsed["start_pdf_page"],
        "end_pdf_page": parsed["end_pdf_page"],
        "vault_chapter_dir": str(ch_vault_dir.resolve()),
        "assets_dir": str((ch_vault_dir / "assets").resolve()),
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
        # Render on demand if outside initial slice
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
        # Convert 0..1000 normalized coordinates to pixel coordinates
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

    result = {
        "cropped_image_path": str(out_path.resolve()),
        "obsidian_embed": f"![[assets/{out_path.name}]]",
        "source_pdf_page": page_num,
        "pixel_box": [left, top, right, bottom],
    }
    print(json.dumps(result, indent=2))


def sanitize_mathjax(markdown_text: str) -> str:
    """
    Ensure Obsidian MathJax compatibility:
    1. Ensure display blocks $$ ... $$ are surrounded by clean newlines.
    2. Strip accidental spaces inside single-line inline math `$ x + y $` -> `$x + y$`.
    """
    # Trim spaces immediately inside inline $...$ (only single-line, non-display math)
    def fix_inline_math(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        return f"${inner}$"

    # Match single `$` not preceded/followed by `$` or `\`
    cleaned = re.sub(
        r"(?<![\\$])\$(?!\$)[ \t]+([^\n$]+?)[ \t]*\$(?!\$)",
        fix_inline_math,
        markdown_text,
    )
    cleaned = re.sub(
        r"(?<![\\$])\$(?!\$)[ \t]*([^\n$]+?)[ \t]+\$(?!\$)",
        fix_inline_math,
        cleaned,
    )
    return cleaned


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

    # Discover all section markdown files in the chapter folder (excluding the MOC itself)
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

        # Replace existing navigation callout if present, or insert after frontmatter / top H1
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

        final_content = f"{body_part.rstrip()}\n\n---\n{USER_NOTES_MARKER}\n"
        if user_notes.strip():
            final_content += f"{user_notes.strip()}\n"

        note_path.write_text(final_content, encoding="utf-8")
        updated_notes.append(note_path.name)
        moc_entries.append(f"- [[{note_path.stem}]]")

    # Build the Chapter MOC file
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

    summary = {
        "moc_path": str(moc_path.resolve()),
        "finalized_section_notes": updated_notes,
        "vault_chapter_dir": str(ch_vault_dir.resolve()),
    }
    print(json.dumps(summary, indent=2))


def main() -> None:
    workspace_root = Path(__file__).resolve().parent
    cfg = load_config(workspace_root)

    parser = argparse.ArgumentParser(
        description="Local PDF & Obsidian Vault Toolkit for Book-Synthesizer"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Check active PDF in ./book/ and target chapter in ./chapter.txt")

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

    p_fin = sub.add_parser("finalize", help="Sanitize MathJax, inject [[Prev]]/[[Next]] links, and build Chapter MOC")
    p_fin.add_argument("--chapter", type=str, default=None, help="Override chapter number")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(workspace_root, cfg)
    elif args.command == "prepare":
        cmd_prepare(workspace_root, cfg, args)
    elif args.command == "crop":
        cmd_crop(workspace_root, cfg, args)
    elif args.command == "finalize":
        cmd_finalize(workspace_root, cfg, args)


if __name__ == "__main__":
    main()
