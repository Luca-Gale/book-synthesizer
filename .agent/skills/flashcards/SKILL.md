---
name: flashcards
description: >-
  Dedicated SectionFlashcardExtractor agent skill. Reads the raw 300-DPI textbook PDF page
  PNGs directly (never summarizing the Obsidian note) and extracts an exhaustive, atomic
  set of Anki flashcards across a 5-Pillar Extraction Taxonomy into .cache/.../cards_X_Y.json,
  then syncs non-destructively via AnkiConnect. Can be invoked standalone via /flashcards
  or orchestrated as Stage B of /synthesize.
---

# Exhaustive Textbook Flashcard Extractor (`/flashcards`)

Use this skill whenever the user says **"flashcards"**, **"generate cards"**, **"refresh flashcards"**, **"update cards"**, **"sync anki"**, or invokes `/flashcards`, OR when invoked as **Stage B (`SectionFlashcardExtractor`)** at the end of `/synthesize`.

> [!IMPORTANT]
> **Architectural Role (`SectionFlashcardExtractor`)**:
> This skill is **strictly decoupled** from Obsidian note synthesis. You can edit the extraction rules, card density, or pedagogical style in this file at any time without affecting how Obsidian Pre-Reading Primer notes are written in [`.agent/skills/synthesize/SKILL.md`](../synthesize/SKILL.md).

---

## Core Flashcard Philosophy

1. **Direct-from-Source Extraction (Never Summarize a Summary)**:
   - **CRITICAL**: Always extract flashcards by visually reading the **raw 300-DPI textbook page PNGs (`page_pngs`)** for section `X.Y`.
   - Never rely solely on the Obsidian `.md` primer note as your source text—the flashcards are the user's primary long-term study medium after reading the chapter. If the user reads the textbook section *after* studying your flashcards, **nothing in the textbook should feel new or omitted**.
   - You may glance at `note_path` or `section_assets` only to verify which cropped figures (`fig_*.png`) are already available in `vault/.../assets/` and to keep symbol conventions consistent.
2. **Exhaustive Coverage + High Density Welcome**:
   - Do **not** artificially cap the number of cards per section. Convert **every notion, definition, equation, derivation step, assumption, physical interpretation, case study, and diagram insight** into flashcards.
   - Creating many cards is explicitly desired: the user prefers comprehensive coverage and can effortlessly suspend any redundant or easy card in Anki during daily reviews.
3. **Strict Atomicity (Minimum Information Principle)**:
   - Exhaustive coverage means **more atomic cards**, never bloated multi-paragraph cards.
   - Each card must test **one clear concept, equation, condition, or diagram relationship**.
   - **Single Cloze Group Rule (`{{c1::...}}` only)**: Every `Cloze` card must use `{{c1::...}}` (never `{{c2::...}}` or `{{c3::...}}`), so 1 JSON entry = 1 atomic Anki review card. If an equation has two distinct parts worth testing separately, create two distinct `Cloze` cards with different `{{c1::...}}` targets.
4. **Deterministic Chronological Reading Order**:
   - **Linear Narrative Traversal**: Extract cards strictly in the **top-to-bottom reading order** of each page, progressing from page $N$ to page $N+1$. Do **NOT** group cards by pillar—emit cards in the exact sequence concepts, equations, and diagrams appear in the textbook so the user can verify them side-by-side in real time while reading.
   - **Atomic Once Rule**: If a symbol, definition, or notation was already carded on an earlier page of the section, do **not** repeat it on later pages unless a new mathematical constraint, boundary condition, or physical nuance is introduced.
   - **Two-Pass Sweep per Section**:
     - *Pass 1 (Chronological Ground Sweep)*: Traverse pages paragraph-by-paragraph, extracting atomic definitions, equations, assumptions, and diagrams as they appear in local context.
     - *Pass 2 (Milestone Synthesis Sweep)*: Attach any high-level cross-page intuition or summary cards to the concluding milestone page where the concept culminates.
   - **Ordering Metadata**: Every card object MUST specify:
     - `"source_page": <int>` (the actual PDF page number, e.g. 89)
     - `"seq": <int>` (1, 2, 3... within that section)
     - `"book_order": "<CC>.<SS>.<PPP>.<NN>"` (e.g. `"04.01.089.01"`, zero-padded for lexicographic sorting)
5. **Non-Destructive Anki Sync**:
   - When refreshing or editing existing cards, preserve the `id` (`ch04_s01_p089_c01`) of any card whose core concept is being refined so `book_tool.py` updates it in-place via `updateNoteFields` without resetting Anki review intervals.
   - Cards omitted during a refresh are never deleted—`book_tool.py` tags them `book_synthesizer::orphaned` and suspends them in Anki.

---

## The 5-Pillar Extraction Taxonomy (Mandatory Sweep)

As you read each 300-DPI textbook page (`pdf_page_XXXX.png`) of section `X.Y`, systematically sweep the text, equations, examples, and figures across all **5 Pillars** as you encounter them linearly down the page, while avoiding trivial linguistic filler:

1. **Pillar 1 — Formal Definitions & Nomenclature (`Basic` or `Cloze`)**:
   - Every newly introduced term, signal class, operator, property, or notation convention.
   - Explicitly include **Notation Traps** (e.g., where the author's notation differs from adjacent fields).
2. **Pillar 2 — Governing Equations, Matrix Structures & Derivation Steps (`Cloze`)**:
   - Every numbered and unnumbered equation, predictor form, criterion function, regressor vector structure, and key algebraic transition step.
   - Wrap the target expression inside the math block or hoist cleanly: e.g., `{{c1::$\hat{y}(t|\theta) = \varphi^T(t)\theta$}}`.
3. **Pillar 3 — Explicit & Implicit Assumptions / Boundary Conditions (`Basic` or `Cloze`)**:
   - Under what exact conditions does an equation or theorem hold? (e.g., linearity, time-invariance, zero-mean white noise, invertibility / persistency of excitation, open-loop vs. closed-loop).
   - What fails physically or mathematically if the assumption is violated?
4. **Pillar 4 — Physical, Geometric & Engineering Intuition (`Basic`)**:
   - *Why* is the model or algorithm formulated this way?
   - What is the physical meaning of each parameter or term in the real-world engineering examples (e.g., thermal storage, aircraft aerodynamics, acoustic filtering)?
5. **Pillar 5 — Visual Diagram, Block Diagram & Plot Interpretation (`Basic` or `Cloze` with Media)**:
   - Every schematic, signal flow graph, block diagram, or experimental data plot in the section.
   - Reuse the cropped figures listed in `section_assets` (`![[assets/fig_...png]]` and `"media": ["fig_...png"]`).
   - **Fallback Cropping**: If you spot a figure on `pdf_page_XXXX.png` that is *not* yet in `section_assets`, crop it yourself via:
     ```powershell
     python book_tool.py crop --page <PDF_PAGE_NUM> --bbox "<ymin>,<xmin>,<ymax>,<xmax>" --out "fig_<X>_<Y>_<short_slug>.png"
     ```

---

## Execution Workflow

### Step 1: Inspect Section Pages, Cropped Assets & Existing Ledger
Run:
```powershell
python book_tool.py refresh-cards [--chapter <X>] [--section <X.Y>]
```
*(Note: If invoked right after `book_tool.py prepare` during `/synthesize`, you already have `manifest.json` and `refresh-cards` output).*

Inspect `sections_to_refresh` in the JSON output:
- `page_pngs`: The exact 300-DPI rendered textbook pages (`pdf_page_XXXX.png`) for section `X.Y`.
- `section_assets`: All cropped figures (`fig_*.png`) already available in `vault/.../assets/` for section `X.Y`.
- `existing_cards`: Currently tracked cards and their `id` / `anki_note_id`.
- `cards_scratch_path`: Target output file (`.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json`).

### Step 2: Parallel Section Flashcard Extraction (`1 Subagent per Section X.Y`)
For 3+ sections, launch parallel subagents via `invoke_subagent` (`TypeName: "self"`, `Role: "Section X.Y Flashcard Extractor"`). For 1–2 sections, execute directly or sequentially.

Each `SectionFlashcardExtractor` subagent MUST:
1. Call `read_file` on **every** 300-DPI page image in `page_pngs` for section `X.Y`.
2. Perform the two-pass linear chronological sweep across the **5-Pillar Extraction Taxonomy**.
3. Write the section flashcard scratch file to `cards_scratch_path` (`.cache/<book_slug>/ch_<XX>/cards_<X>_<Y>.json`) using this schema:

```json
{
  "section": "<X.Y>",
  "section_title": "<Clean Section Title>",
  "cards": [
    {
      "id": "ch0<X>_s0<Y>_p089_c01",
      "book_order": "0<X>.0<Y>.089.01",
      "source_page": 89,
      "seq": 1,
      "model": "Basic",
      "pillar": "intuition",
      "front": "What is the physical and mathematical role of $e(t)$ in the ARX model structure?",
      "back": "$e(t)$ represents the **equation error** (or innovation disturbance) entering directly into the difference equation:\n$$A(q)y(t) = B(q)u(t) + e(t)$$\nIt is assumed to be zero-mean white noise with variance $\\lambda$.",
      "tags": ["arx", "assumptions", "pillar-intuition"],
      "media": []
    },
    {
      "id": "ch0<X>_s0<Y>_p089_c02",
      "book_order": "0<X>.0<Y>.089.02",
      "source_page": 89,
      "seq": 2,
      "model": "Cloze",
      "pillar": "equations",
      "front": "In linear regression $\\hat{y}(t|\\theta) = \\varphi^T(t)\\theta$, the least-squares estimate minimizing $V_N(\\theta)$ is given by {{c1::$\\hat{\\theta}_N = \\left[\\sum_{t=1}^N \\varphi(t)\\varphi^T(t)\\right]^{-1} \\sum_{t=1}^N \\varphi(t)y(t)$}}.",
      "back": "![[assets/fig_1_1_system_signals.png]]\nRequires the regression matrix $\\sum_{t=1}^N \\varphi(t)\\varphi^T(t)$ to be invertible (persistency of excitation).",
      "tags": ["least-squares", "derivation", "pillar-equations"],
      "media": ["fig_1_1_system_signals.png"]
    }
  ]
}
```

### Step 3: Aggregate & Sync to AnkiConnect
Once all `cards_<X>_<Y>.json` files are written, run in the main agent thread:
```powershell
python book_tool.py sync-anki [--chapter <X>] [--section <X.Y>]
```
*(Or `python book_tool.py finalize` if running at the end of a full chapter synthesis).*
