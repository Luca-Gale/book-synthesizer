# Book-Synthesizer

An **Antigravity-native** workflow and deterministic Python toolkit that transforms dense engineering, physics, and mathematics textbooks into section-by-section (`1.1`, `1.2`, ...) **Obsidian Pre-Reading Primer Notes**.

It preserves physical intuition, complete mathematical derivations in standard LaTeX/MathJax, and automatically crops high-resolution (300 DPI) textbook diagrams into note assets.

---

## Key Features

- **Pedagogical Pre-Reading Primers**: Notes structured around *The Big Idea*, *Notation & Conventions*, *Rigorous Derivations*, *Interpreting the Math*, and *Common Traps & Edge Cases*.
- **Zero API Keys Required**: Driven entirely through Antigravity workspace skills with local document processing via `PyMuPDF` and `Pillow`.
- **Vision-Guided Figure Cropping**: Crops figures and block diagrams directly from 300-DPI renders with automatic safety padding and embeds them cleanly into Obsidian markdown (`![[fig_...png]]`).
- **Bidirectional Note Linking**: Automatically wires navigation links (`[[Previous Section]]`, `[[00 - Chapter MOC]]`, `[[Next Section]]`) across all section notes.
- **User Notes Preservation**: Any notes you add under `<!-- USER NOTES BELOW THIS LINE -->` are preserved across re-synthesis runs.
- **Ready-to-Use Obsidian Vault**: Built-in `.obsidian/` configuration pre-equipped with styles and settings for Dataview, MathLinks, LaTeX Suite, and Image Toolkit.

---

## Prerequisites

- **Python**: 3.10+
- **Python Libraries**:
  ```bash
  pip install pymupdf pillow
  ```
- **Obsidian** (optional, recommended for viewing and browsing notes).

---

## Quick Start (3 Steps)

1. **Drop your textbook PDF** into the [`book/`](./book/) folder (e.g. `book/linear_systems.pdf`).
2. **Set the target chapter number** in [`chapter.txt`](./chapter.txt) (e.g. `1`).
3. **Ask Antigravity in chat**:
   > `Synthesize the chapter` *(or invoke the `/synthesize` skill)*

Antigravity will inspect the chapter, render the pages, extract sections, generate LaTeX notes with cropped figures, wire navigation links, and generate the Chapter Map of Content (MOC).

---

## Repository Structure

```text
book-synthesizer/
├── .agent/
│   └── skills/
│       └── synthesize/        # Antigravity synthesis workflow definition
│           └── SKILL.md
├── book/                      # Active textbook PDF directory (ignored in git)
│   └── DROP_YOUR_TEXTBOOK_PDF_HERE.txt
├── vault/                     # Ready-to-open Obsidian vault
│   ├── .obsidian/             # Pre-configured Obsidian settings & plugins
│   └── <Book Title>/
│       └── Chapter 01 - <Title>/
│           ├── 00 - Chapter 01 MOC.md
│           ├── 1.1 Dynamic Systems.md
│           ├── 1.2 Models.md
│           └── assets/
│               └── fig_1_1_system_signals.png
├── .cache/                    # Rendered 300-DPI page PNGs & manifests (ignored)
├── book_tool.py               # Deterministic PDF processing & vault CLI
├── chapter.txt                # Active chapter selector (e.g. 1)
├── config.json                # Customization parameters
├── TECH_SPEC.md               # Technical specification and architecture
└── README.md
```

---

## `book_tool.py` CLI Reference

While Antigravity handles orchestration automatically, you can run `book_tool.py` directly from your terminal:

### 1. Check Workspace Status
Inspects the detected textbook PDF in `book/` and active chapter in `chapter.txt`:
```bash
python book_tool.py status
```

### 2. Prepare Chapter Pages & Manifest
Detects section headings, page ranges, and renders 300-DPI page images into `.cache/`:
```bash
python book_tool.py prepare [--chapter N]
```

### 3. Crop a Figure
Crops a bounding box `[ymin, xmin, ymax, xmax]` (normalized $0$–$1000$) from a rendered page:
```bash
python book_tool.py crop --page <pdf_page_num> --box <ymin> <xmin> <ymax> <xmax> --out <filename.png>
```

### 4. Finalize Chapter Notes & Build MOC
Sanitizes LaTeX delimiters, wires `[[Prev]]`/`[[Next]]` links, preserves user notes, and generates the Chapter Map of Content:
```bash
python book_tool.py finalize [--chapter N]
```

---

## Customization (`config.json`)

You can customize tool behavior via [`config.json`](./config.json):

```json
{
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
    "appendix",
    "index"
  ]
}
```

---

## Obsidian Integration

The [`vault/`](./vault/) folder is a fully functional Obsidian vault:
- Open Obsidian and select **"Open folder as vault"** pointing to `vault/`.
- Pre-installed plugins include **Obsidian LaTeX Suite** (inline math shortcuts), **MathLinks**, **Dataview**, **Image Toolkit** (click-to-zoom for textbook diagrams), and **Table Editor**.
- If you already have an existing vault, you can drag and drop any `<Book Title>` folder into your existing vault without breaking note links or asset paths.
