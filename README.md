# Book-Synthesizer

An **Antigravity-native** workflow and deterministic Python toolkit that transforms dense engineering, physics, and mathematics textbooks into:
1. Section-by-section (`1.1`, `1.2`, ...) **Obsidian Pre-Reading Primer Notes** (preserving physical intuition, complete mathematical derivations in LaTeX/MathJax, and cropped 300-DPI textbook diagrams).
2. Comprehensive **Anki Flashcard Decks** (`Basic` & `Cloze` with MathJax + diagrams) synced non-destructively via **AnkiConnect**.

---

## Key Features

- **Strict Separation of Concerns**: Clean, distraction-free reading notes in Obsidian (`vault/`); active-recall flashcards in Anki managed via a local JSON ledger (`decks/`).
- **Non-Destructive AnkiConnect Sync**: Updates existing flashcards in place (`updateNoteFields`) without resetting your learning intervals or ease factors. Superseded/orphaned cards are safely auto-suspended (`book_synthesizer::orphaned`) rather than deleted, so you can re-enable any card you liked.
- **Decoupled Card Refresh**: Refresh, expand, or polish flashcards for any section or chapter on demand without re-synthesizing the Obsidian chapter notes.
- **Zero API Keys Required**: Driven entirely through Antigravity workspace skills with local document processing via `PyMuPDF` and `Pillow`.
- **Vision-Guided Figure Cropping**: Crops figures and block diagrams directly from 300-DPI renders with automatic safety padding, embedding them inline in Obsidian and uploading them automatically to Anki's media folder (`storeMediaFile`).
- **Bidirectional Note Linking & User Notes Preservation**: Automatically wires navigation links (`[[Prev]]`, `[[MOC]]`, `[[Next]]`) and preserves personal notes under `<!-- USER NOTES BELOW THIS LINE -->`.

---

## Prerequisites

- **Python**: 3.10+
- **Python Libraries**:
  ```bash
  pip install pymupdf pillow
  ```
- **Obsidian** (recommended for viewing and browsing primer notes).
- **Anki Desktop + AnkiConnect Add-on** (for live flashcard synchronization):
  1. Open Anki Desktop $\to$ **Tools** $\to$ **Add-ons** $\to$ **Get Add-ons...**
  2. Enter code: **`2055492159`**
  3. Restart Anki. *(If Anki is closed during synthesis, flashcards are staged locally in `decks/` and synced whenever you run `python book_tool.py sync-anki`.)*

---

## Quick Start

### 1. Synthesize a Chapter (Notes + Flashcards)
1. **Drop your textbook PDF** into [`book/`](./book/).
2. **Set the target chapter number** in [`chapter.txt`](./chapter.txt) (e.g. `1`).
3. **Ask Antigravity in chat**:
   > `Synthesize the chapter` *(or invoke `/synthesize`)*

### 2. Generate, Refresh, or Fine-Tune Flashcards Independently (`/flashcards`)
Flashcard generation is strictly decoupled into [`.agent/skills/flashcards/SKILL.md`](./.agent/skills/flashcards/SKILL.md) (`SectionFlashcardExtractor`), which reads the raw 300-DPI textbook pages directly across a **5-Pillar Extraction Taxonomy**. Without re-synthesizing your Obsidian reading notes, you can invoke `/flashcards` or ask in chat:
- *"Run `/flashcards` for Chapter 1"*
- *"Refresh flashcards for section 1.3"*
- *"Add 3 flashcards on the projection theorem in section 1.3"*

---

## Repository Structure

```text
book-synthesizer/
├── .agent/
│   └── skills/
│       ├── synthesize/        # Stage A: SectionNoteSynthesizer & Pipeline Orchestrator
│       │   └── SKILL.md
│       └── flashcards/        # Stage B: Standalone SectionFlashcardExtractor (5-Pillar Taxonomy)
│           └── SKILL.md
├── book/                      # Active textbook PDF directory (ignored in git)
├── vault/                     # Ready-to-open Obsidian vault (clean reading notes)
│   ├── .obsidian/             # Pre-configured Obsidian settings & plugins
│   └── <Book Title>/
│       └── Chapter 01 - <Title>/
│           ├── 00 - Chapter 01 MOC.md
│           ├── 1.1 Dynamic Systems.md
│           └── assets/
│               └── fig_1_1_system_signals.png
├── decks/                     # Structured JSON flashcard ledgers per chapter
│   └── <book_slug>/
│       └── ch_01_cards.json
├── .cache/                    # Rendered 300-DPI page PNGs & section scratch files
├── book_tool.py               # Deterministic PDF, Vault & AnkiConnect CLI
├── chapter.txt                # Active chapter selector (e.g. 1)
├── config.json                # Customization parameters
├── TECH_SPEC.md               # Technical specification (Red-Team Validated)
├── RED_TEAM_AUDIT.md          # Architectural audit log
└── README.md
```

---

## `book_tool.py` CLI Reference

### 1. Check Workspace & AnkiConnect Status
```bash
python book_tool.py status
```

### 2. Prepare Chapter Pages & Manifest
```bash
python book_tool.py prepare [--chapter N]
```

### 3. Crop a Figure
```bash
python book_tool.py crop --page <pdf_page_num> --bbox "<ymin>,<xmin>,<ymax>,<xmax>" --out <filename.png>
```

### 4. Finalize Chapter Notes, Build MOC & Sync Anki
```bash
python book_tool.py finalize [--chapter N] [--notes-only]
```

### 5. Sync Flashcards to AnkiConnect
Aggregates section flashcards into `decks/<book_slug>/ch_XX_cards.json` and syncs non-destructively with Anki:
```bash
python book_tool.py sync-anki [--chapter N] [--section X.Y] [--force] [--prune]
```

### 6. Inspect Raw Page PNGs, Cropped Assets & Card Ledger for Flashcards
Exposes the 300-DPI section page PNGs, cropped figure assets, and current deck ledger for standalone flashcard extraction:
```bash
python book_tool.py refresh-cards [--chapter N] [--section X.Y]
# or alias:
python book_tool.py cards [--chapter N] [--section X.Y]
```
