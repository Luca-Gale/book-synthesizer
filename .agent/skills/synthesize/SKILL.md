---
name: synthesize
description: >-
  Synthesize the active textbook chapter specified in chapter.txt (from the PDF in book/)
  into dedicated section-by-section (X.1, X.2, ...) Obsidian Pre-Reading Primer notes,
  preserving full mathematical rigor (LaTeX), physical intuition, and cropped textbook diagrams.
---

# Textbook Chapter Synthesizer (`/synthesize`)

Use this skill whenever the user says **"synthesize"**, **"run"**, **"summarize the chapter"**, or invokes `/synthesize`.

---

## Core Principles

1. **Zero Friction Input**:
   - Never ask the user for the PDF path or chapter number unless `book/` is empty.
   - Always read the active PDF from `./book/*.pdf` and the target chapter number `X` from `./chapter.txt` via `python book_tool.py prepare`.
2. **Granularity = Numbered Section (`X.1`, `X.2`, ..., `X.k`)**:
   - Every main numbered section of Chapter `X` (`1.1`, `1.2`, `1.3`, ...) gets **1 dedicated Obsidian `.md` file**.
   - Deeper sub-subsections (`1.3.1`, `1.3.2`) stay **inside** `1.3 <Title>.md` as `###` headings.
   - **Automatically ignore** non-primer sections: *Bibliography*, *References*, *Problems*, *Exercises*, *Historical Notes*, *Appendices*.
3. **No Verbatim Source Dumps**:
   - Do **not** copy-paste verbatim textbook paragraphs at the bottom of the note.
   - The note must act as a **comprehensive Pre-Reading Primer** (Intuition + Complete Mathematical Rigor + Cropped Figures + Pre-Reading Compass) that prepares the user before they read the actual section in the book.

---

## Step-by-Step Execution Workflow

### Step 1: Prepare & Slice the Target Chapter
1. Run `python book_tool.py prepare` (using `BypassSandbox: true` if Windows `exebox` sandbox is unsupported on the host OS).
2. Inspect the JSON output (`manifest.json`):
   - Check if `active_sections_to_synthesize` accurately lists the chapter's numbered sections (`X.1`, `X.2`, ...) and their PDF page ranges.
   - **Fallback if PDF Bookmarks Were Missing**: If `active_sections_to_synthesize` is empty or incomplete because the PDF lacks section bookmarks, use `read_file` to inspect the first rendered page(s) or Table of Contents pages in `.cache/<book>/ch_<XX>/pages/`, visually identify the 1-based PDF start/end pages of Chapter `X` and its `X.Y` sections, and re-run:
     `python book_tool.py prepare --pages <START_PDF_PAGE>-<END_PDF_PAGE> --chapter-title "<Chapter Title>"`

### Step 2: Parallel Section Synthesis (`1 Subagent per Section X.Y`)
For each non-skipped section `X.Y` in the chapter (either via parallel `invoke_subagent` calls with `TypeName: "self"` for chapters with 3+ sections, or sequentially for 1–2 sections):

1. **Visually Read the Section Pages**:
   - Call `read_file` on the rendered 300-DPI PNG images (`pdf_page_XXXX.png`) covering section `X.Y`.
2. **Crop Key Textbook Figures & Block Diagrams**:
   - Whenever section `X.Y` contains a figure, plot, signal flow graph, or schematic, estimate its normalized `[ymin, xmin, ymax, xmax]` coordinates (`0` to `1000` scale) on `pdf_page_XXXX.png` and run:
     ```powershell
     python book_tool.py crop --page <PDF_PAGE_NUM> --bbox "<ymin>,<xmin>,<ymax>,<xmax>" --out "fig_<X>_<Y>_<short_slug>.png"
     ```
   - Inspect the cropped PNG in `vault/.../assets/` with `read_file` if needed to verify no axis labels were clipped.
3. **Write the Dedicated Section Primer Note (`<vault_chapter_dir>/<X.Y> <Clean Section Title>.md`)**:
   - Write the note using the exact structure below:

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
  - **CRITICAL**: Always ensure there is a space BEFORE the opening `$` and AFTER the closing `$` when adjacent to surrounding words, parentheses, or markdown bold/italic formatting (e.g. write `at time $t$ for all $t \ge 0$`, NEVER `at time$t$for all$t \ge 0$`). Do not let `$` touch adjacent letters or words. Trailing sentence punctuation (`$x$,` or `$x$.`) is allowed without a space.
  - Format display math blocks with `$$` on dedicated lines separated by blank lines.

---

## 3. Pre-Reading Compass (What to Watch Out For)
> [!warning] Key Conceptual Leaps & Notation Traps
> - **Leap 1**: ...
> - **Notation Trap**: ...
> - **Questions to Keep in Mind While Reading**: ...

---
<!-- USER NOTES BELOW THIS LINE -->
```

### Step 3: Finalize Vault Links & Chapter MOC
1. Once all `X.Y` section notes for Chapter `X` are written, run:
   ```powershell
   python book_tool.py finalize
   ```
2. This automatically:
   - Generates `00 - Chapter XX MOC.md` linking all section notes in order.
   - Injects `← [[Prev]] | [[Chapter X MOC]] | [[Next]] →` navigation headers into every section note.
   - Sanitizes MathJax syntax and preserves any existing notes below `<!-- USER NOTES BELOW THIS LINE -->`.
3. Present a concise summary to the user with clickable links to the generated MOC and section notes.
