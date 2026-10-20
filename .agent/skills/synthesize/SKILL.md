---
name: synthesize
description: >-
  Synthesize the active textbook chapter specified in chapter.txt (from the PDF in book/)
  into dedicated section-by-section (X.1, X.2, ...) Obsidian Pre-Reading Primer notes
  and high-yield Anki flashcards synced non-destructively via AnkiConnect. Also supports
  refreshing, adding, or editing flashcards independently without re-synthesizing notes.
---

# Textbook Chapter Synthesizer & Anki Flashcard Engine (`/synthesize`)

Use this skill whenever the user says **"synthesize"**, **"run"**, **"summarize the chapter"**, **"generate/refresh flashcards"**, **"sync anki"**, or invokes `/synthesize`.

---

## Core Principles

1. **Zero Friction Input**:
   - Never ask the user for the PDF path or chapter number unless `book/` is empty.
   - Always read the active PDF from `./book/*.pdf` and the target chapter number `X` from `./chapter.txt` via `python book_tool.py prepare` (or `python book_tool.py refresh-cards` when only working on flashcards).
2. **Strict Separation of Concerns (Notes in Obsidian, Flashcards in Anki)**:
   - Every main numbered section of Chapter `X` (`1.1`, `1.2`, `1.3`, ...) gets **1 dedicated, distraction-free Obsidian `.md` file** in `vault/`. Never clutter the reading note with flashcard Q&A blocks.
   - All flashcards for section `X.Y` are written to `.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json`, which `book_tool.py` aggregates into `decks/<book_slug>/ch_<XX>_cards.json` and syncs to Anki (`Textbooks::<Book Name>::Chapter <XX>::<X.Y Section Title>`) via **AnkiConnect**.
3. **Comprehensive High-Yield Flashcard Extraction**:
   - Do not artificially cap the number of cards per section: **convert everything worth remembering into a flashcard** (core definitions, governing equations, physical/geometric intuition, key assumptions, notation meanings, and diagram interpretations).
   - Mix **`Basic`** cards (conceptual Q&A, physical intuition, assumptions, diagram reading) and **`Cloze`** cards (`{{c1::...}}` for equations, matrix structures, and precise conditions).
4. **Non-Destructive Anki Sync**:
   - Updating a card's wording or equations preserves its `id` and `anki_note_id`, invoking `updateNoteFields` so Anki **100% preserves review intervals and ease factors**.
   - Cards removed on a refresh are never hard-deleted automatically; they are tagged `book_synthesizer::orphaned` and **auto-suspended** in Anki so they leave the daily review queue while remaining recoverable.

---

## Workflow A: Full Chapter Synthesis (Obsidian Primers + Anki Flashcards)

### Step 1: Prepare & Slice the Target Chapter
1. Run `python book_tool.py prepare`.
2. Inspect the JSON output (`manifest.json`):
   - Check if `active_sections_to_synthesize` accurately lists the chapter's numbered sections (`X.1`, `X.2`, ...) and their PDF page ranges.
   - **Fallback if PDF Bookmarks Were Missing**: Visually inspect the first rendered page(s) or Table of Contents pages in `.cache/<book>/ch_<XX>/pages/` with `read_file`, identify the 1-based PDF start/end pages of Chapter `X`, and re-run:
     `python book_tool.py prepare --pages <START_PDF_PAGE>-<END_PDF_PAGE> --chapter-title "<Chapter Title>"`

### Step 2: Parallel Section Synthesis (`1 Subagent per Section X.Y`)
For each non-skipped section `X.Y` in the chapter (via parallel `invoke_subagent` calls with `TypeName: "self"` for 3+ sections, or sequentially for 1–2 sections):

1. **Visually Read the Section Pages**:
   - Call `read_file` on the rendered 300-DPI PNG images (`pdf_page_XXXX.png`) covering section `X.Y`.
2. **Crop Key Textbook Figures & Block Diagrams**:
   - Whenever section `X.Y` contains a figure, plot, signal flow graph, or schematic, estimate its normalized `[ymin, xmin, ymax, xmax]` coordinates (`0` to `1000` scale) on `pdf_page_XXXX.png` and run:
     ```powershell
     python book_tool.py crop --page <PDF_PAGE_NUM> --bbox "<ymin>,<xmin>,<ymax>,<xmax>" --out "fig_<X>_<Y>_<short_slug>.png"
     ```
   - Inspect the cropped PNG in `vault/.../assets/` with `read_file` to verify no axis labels were clipped.
3. **Write the Dedicated Section Primer Note (`<vault_chapter_dir>/<X.Y> <Clean Section Title>.md`)**:
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

---

## 3. Pre-Reading Compass (What to Watch Out For)
> [!warning] Key Conceptual Leaps & Notation Traps
> - **Leap 1**: ...
> - **Notation Trap**: ...
> - **Questions to Keep in Mind While Reading**: ...

---
<!-- USER NOTES BELOW THIS LINE -->
```

4. **Write the Section Flashcards Scratch File (`.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json`)**:
   - Extract **everything worth remembering** from section `X.Y` into high-yield flashcards and save to the `cards_scratch_path` specified in `manifest.json`:
   ```json
   {
     "section": "<X.Y>",
     "section_title": "<Clean Section Title>",
     "cards": [
       {
         "id": "ch0<X>_s<X>_<Y>_c01",
         "model": "Basic",
         "front": "What is the physical and mathematical role of $e(t)$ in the ARX model structure?",
         "back": "$e(t)$ represents the **equation error** (or innovation disturbance) entering directly into the difference equation:\n$$A(q)y(t) = B(q)u(t) + e(t)$$\nIt is assumed to be zero-mean white noise with variance $\\lambda$.",
         "tags": ["arx", "assumptions"],
         "media": []
       },
       {
         "id": "ch0<X>_s<X>_<Y>_c02",
         "model": "Cloze",
         "front": "In linear regression $\\hat{y}(t|\\theta) = \\varphi^T(t)\\theta$, the least-squares estimate minimizing $V_N(\\theta)$ is given by {{c1::$\\hat{\\theta}_N = \\left[\\sum_{t=1}^N \\varphi(t)\\varphi^T(t)\\right]^{-1} \\sum_{t=1}^N \\varphi(t)y(t)$}} provided that {{c2::the regression matrix is invertible (persistency of excitation)}}.",
         "back": "![[assets/fig_1_1_system_signals.png]]\nThe regressor vector $\\varphi(t)$ contains past inputs and outputs.",
         "tags": ["least-squares", "derivation"],
         "media": ["fig_1_1_system_signals.png"]
       }
     ]
   }
   ```
   - *Note*: `book_tool.py` automatically converts `$...$` / `$$...$$` to Anki's `\(...\)` / `\[...\]` with HTML-safe escaping (`&lt;`, `&gt;`, `&amp;`), and automatically uploads any cropped figures in `media` or `![[assets/...]]` to Anki's media folder via `storeMediaFile`.

### Step 3: Finalize Vault Links, Chapter MOC & Sync to AnkiConnect
1. Once all `X.Y` section notes and `cards_<X>_<Y>.json` files are written, run in the main agent thread:
   ```powershell
   python book_tool.py finalize
   ```
2. This single-threaded command automatically:
   - Generates `00 - Chapter XX MOC.md` and injects `← [[Prev]] | [[Chapter X MOC]] | [[Next]] →` navigation headers.
   - Sanitizes Obsidian MathJax syntax and preserves user notes below `<!-- USER NOTES BELOW THIS LINE -->`.
   - Aggregates all `.cache/.../cards_<X>_<Y>.json` files into `decks/<book_slug>/ch_<XX>_cards.json`.
   - Connects to **AnkiConnect** (`127.0.0.1:8765`), uploads cropped figure media, creates the nested subdecks (`Textbooks::<Book>::Chapter XX::<X.Y Title>`), adds new cards, updates modified cards via `updateNoteFields`, and suspends any orphaned cards (or stages them offline if Anki is closed).

---

## Workflow B: Independent Flashcard Refresh, Generation, or Editing (Without Re-Synthesizing Notes)

Whenever the user asks to **generate flashcards for an already-synthesized chapter**, **refresh flashcards** to keep revision fresh, or **add/modify specific cards** without touching the Obsidian notes:

1. **Inspect Existing Notes & Current Ledger**:
   ```powershell
   python book_tool.py refresh-cards [--chapter <X>] [--section <X.Y>]
   ```
2. **Read & Extract / Refine Cards**:
   - Read the existing Obsidian `.md` primer note(s) listed in `sections_to_refresh` using `read_file`.
   - Inspect `existing_cards` for that section:
     - When **modifying or polishing** an existing card, **keep its `id`** (e.g. `ch01_s1_3_c02`) so Anki updates it in-place without resetting its learning interval.
     - When **adding** new cards, assign the next sequential `id`.
     - When **replacing or retiring** a card, omit it from the updated `cards` array—`book_tool.py` will automatically suspend it in Anki (`book_synthesizer::orphaned`) so the user never loses it permanently and can manually un-suspend it if desired.
   - Write the updated `.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json` file(s).
3. **Sync to Anki**:
   ```powershell
   python book_tool.py sync-anki [--chapter <X>] [--section <X.Y>]
   ```
