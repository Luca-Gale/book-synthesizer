---
name: synthesize
description: >-
  Orchestrate textbook chapter synthesis for the chapter specified in chapter.txt (from the PDF
  in book/) using a strictly decoupled two-stage agent pipeline: Stage A (SectionNoteSynthesizer)
  builds section-by-section (X.1, X.2, ...) Obsidian Pre-Reading Primer notes and crops diagrams;
  Stage B (SectionFlashcardExtractor, defined in .agent/skills/flashcards/SKILL.md) independently
  reads the raw 300-DPI textbook pages to extract exhaustive Anki flashcards synced via AnkiConnect.
---

# Textbook Chapter Synthesizer & Pipelined Orchestrator (`/synthesize`)

Use this skill whenever the user says **"synthesize"**, **"run"**, **"summarize the chapter"**, **"synthesize notes"**, or invokes `/synthesize`.
For standalone flashcard generation, refreshing, or fine-tuning without touching Obsidian notes, use the dedicated [`/flashcards` skill](../flashcards/SKILL.md).

---

## Core Architectural Principles

1. **Zero Friction Input**:
   - Never ask the user for the PDF path or chapter number unless `book/` is empty.
   - Always read the active PDF from `./book/*.pdf` and the target chapter number `X` from `./chapter.txt` via `python book_tool.py prepare`.
2. **Strict Two-Agent Decoupling (`SectionNoteSynthesizer` $\neq$ `SectionFlashcardExtractor`)**:
   - **Stage A (`SectionNoteSynthesizer` — defined in this file)**: Focuses 100% of its cognitive and token budget on writing distraction-free, mathematically rigorous Obsidian Pre-Reading Primer notes (`vault/.../<X.Y> <Title>.md`) and cropping textbook diagrams (`python book_tool.py crop`). **It never writes flashcards.**
   - **Stage B (`SectionFlashcardExtractor` — defined in [`.agent/skills/flashcards/SKILL.md`](../flashcards/SKILL.md))**: Runs as a separate, dedicated agent stage after Stage A. It reads the **raw 300-DPI textbook page PNGs directly** (never summarizing the Obsidian note) while reusing Stage A's cropped figures (`assets_manifest.json`).
   - This separation allows you to fine-tune the note synthesis prompt in this file without affecting flashcard generation, or fine-tune flashcard generation in `.agent/skills/flashcards/SKILL.md` without affecting note synthesis.

---

## Workflow A: Full Chapter Synthesis (Stage A Notes $\longrightarrow$ Stage B Flashcards)

### Step 1: Prepare & Slice the Target Chapter
1. Run `python book_tool.py prepare`.
2. Inspect the JSON output (`manifest.json`):
   - Check that `active_sections_to_synthesize` accurately lists the chapter's numbered sections (`X.1`, `X.2`, ...) and their `page_pngs`.
   - **Fallback if PDF Bookmarks Were Missing**: Visually inspect the first rendered page(s) or Table of Contents pages in `.cache/<book>/ch_<XX>/pages/` with `read_file`, identify the 1-based PDF start/end pages of Chapter `X`, and re-run:
     `python book_tool.py prepare --pages <START_PDF_PAGE>-<END_PDF_PAGE> --chapter-title "<Chapter Title>"`

---

### Step 2 — Stage A: Parallel Section Note Synthesis (`SectionNoteSynthesizer`)
For each non-skipped section `X.Y` in `active_sections_to_synthesize` (via parallel `invoke_subagent` calls with `TypeName: "self"`, `Role: "Section X.Y Note Synthesizer"` for 3+ sections, or sequentially for 1–2 sections):

> [!IMPORTANT]
> **Single Responsibility Rule for Stage A**: Each `SectionNoteSynthesizer` subagent ONLY crops figures and writes the Obsidian `.md` primer note. Do **NOT** ask Stage A subagents to generate flashcards.

1. **Visually Read the Section Pages**:
   - Call `read_file` on the rendered 300-DPI PNG images listed in `page_pngs` for section `X.Y`.
2. **Crop Key Textbook Figures & Block Diagrams**:
   - Whenever section `X.Y` contains a figure, plot, signal flow graph, or schematic, estimate its normalized `[ymin, xmin, ymax, xmax]` coordinates (`0` to `1000` scale) on `pdf_page_XXXX.png` and run:
     ```powershell
     python book_tool.py crop --page <PDF_PAGE_NUM> --bbox "<ymin>,<xmin>,<ymax>,<xmax>" --out "fig_<X>_<Y>_<short_slug>.png"
     ```
   - `book_tool.py crop` saves the PNG into `vault/.../assets/` AND registers it in `.cache/<book>/ch_<XX>/assets_manifest.json` so Stage B (`SectionFlashcardExtractor`) can automatically discover and reuse it.
   - Inspect the cropped PNG in `vault/.../assets/` with `read_file` to verify no axis labels were clipped.
3. **Write the Dedicated Section Primer Note (`note_path`)**:
   - Follow this exact structure:

```markdown
---
book: "<Book Name>"
chapter: <X>
section: "<X.Y>"
title: "<Section Title>"
pages: "<Start>–<End>"
tags:
  - textbook-primer
  - chapter-<X>
---

# <X.Y> <Section Title>

> [!tip] Pre-Reading Primer
> **Role in Chapter <X>**: <1–2 sentence high-level takeaway of what this section accomplishes and how it connects to the previous section.>

---

## 1. Core Intuition & Engineering Motivation
- Explain the physical, dynamical, or conceptual reality being modeled in clear, intuitive prose.
- Answer *why* the author introduces these concepts before introducing the formalism.
- Use concrete engineering analogies or mental models where helpful.

---

## 2. Mathematical Rigor & Derivations

### 2.1 Symbol & Variable Glossary
| Symbol | Meaning / Physical Interpretation | Space / Dimensions |
| :--- | :--- | :--- |
| $y(t)$ | ... | $\mathbb{R}^p$ |

### 2.2 Formal Definitions, Assumptions & Step-by-Step Derivations
- Walk through every mathematical formulation, model structure, or proof in the section without skipping algebraic or conceptual steps.
- If the section contains sub-subsections (`<X.Y.1>`, `<X.Y.2>`), give each its own `### <X.Y.1> <Sub-title>` heading.
- Explicitly highlight every **assumption** (e.g., linearity, time-invariance, zero-mean white noise, invertibility) required for the equations to hold.
- **Inline Visual Walkthroughs & Cropped Diagrams**:
  - **CRITICAL**: Never isolate figures at the end of the note. Embed every cropped textbook figure (`![[assets/fig_<X>_<Y>_<slug>.png]]`) **directly inline within the exact subsection or paragraph** where that physical system, block diagram, signal plot, or derivation is introduced.
  - Immediately beneath each embedded figure, include a concise **How to Read This Diagram** walkthrough explaining the axes, blocks, signal flows, or geometry and how they map to the surrounding equations.
- **Strict Obsidian MathJax & Whitespace Discipline**:
  - Format inline math as `$inline$` (no spaces immediately inside the `$` delimiters).
  - Always ensure there is a space BEFORE the opening `$` and AFTER the closing `$` when adjacent to surrounding words, parentheses, or markdown bold/italic formatting.
  - Format display math blocks with `$$` on dedicated lines separated by blank lines.
  - **Display Math inside Callouts (`> [!tip]`, `> [!warning]`, etc.)**:
    - Every line inside a callout MUST maintain the blockquote prefix `> ` (including blank lines, the opening `> $$`, the equation lines `> equation`, and the closing `> $$`).
    - **Never** leave an empty line without `>` or a bare `$$` without `>` inside a callout—doing so abruptly terminates the callout box and breaks the layout.
    - **Never** write `>` as part of the equation body—prefix each line with `> ` at the start of the line so Obsidian's Markdown parser strips the `>` before handing the clean LaTeX to MathJax/KaTeX.

---

## 3. Pre-Reading Compass (What to Watch Out For)
> [!warning] Key Conceptual Leaps & Notation Traps
> - **Leap 1**: ...
> - **Notation Trap**: ...
> - **Questions to Keep in Mind While Reading**: ...

---
<!-- USER NOTES BELOW THIS LINE -->
```

---

### Step 3 — Stage B: Parallel Exhaustive Flashcard Extraction (`SectionFlashcardExtractor`)
Once Stage A completes (unless the user explicitly requested `notes-only`), execute the [`/flashcards` skill (`c:\Users\lucag\OneDrive\Desktop\book-synthesizer\.agent\skills\flashcards\SKILL.md`)](../flashcards/SKILL.md):

1. Read `.agent/skills/flashcards/SKILL.md` and run `python book_tool.py refresh-cards` to get each section's `page_pngs` and newly cropped `section_assets`.
2. Dispatch dedicated `SectionFlashcardExtractor` subagents (`Role: "Section X.Y Flashcard Extractor"`) that read the **raw 300-DPI textbook page PNGs (`page_pngs`) directly** and apply the **5-Pillar Extraction Taxonomy** defined in `.agent/skills/flashcards/SKILL.md` to write `.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json`.

---

### Step 4: Finalize Vault Links, Chapter MOC & Sync to AnkiConnect
1. Once all notes and `cards_<X>_<Y>.json` files are written, run in the main agent thread:
   ```powershell
   python book_tool.py finalize
   ```
2. This single-threaded command automatically:
   - Generates `00 - Chapter XX MOC.md` and injects `← [[Prev]] | [[Chapter X MOC]] | [[Next]] →` navigation headers.
   - Sanitizes Obsidian MathJax syntax and preserves user notes below `<!-- USER NOTES BELOW THIS LINE -->`.
   - Aggregates all `.cache/.../cards_<X>_<Y>.json` files into `decks/<book_slug>/ch_<XX>_cards.json` and syncs non-destructively to Anki via **AnkiConnect** (`127.0.0.1:8765`).

---

## Workflow B: Notes-Only Synthesis or Note Fine-Tuning (`notes-only`)

Whenever the user asks to **only synthesize or refine the Obsidian notes** without generating or touching Anki flashcards:
1. Run **Step 1** (`python book_tool.py prepare`) and **Step 2 (Stage A: `SectionNoteSynthesizer`)** only.
2. Finalize the Obsidian vault without triggering Anki sync:
   ```powershell
   python book_tool.py finalize --notes-only
   ```
