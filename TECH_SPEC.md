# Technical Specification: Deterministic Chronological Flashcards for Reading-Time Verification

- **Status**: `FINAL — Red-Team Validated`
- **Last Updated**: 2026-10-30
- **Scope**: Applied to Chapters 04, 05, and subsequent chapters. Prior chapters (1–3) remain untouched unless explicitly refreshed.

---

## 1. Overview & Core Problem
- **Problem Statement**: During first-time reading of a textbook chapter, the user keeps Anki in sight as a real-time safety check on AI-generated flashcards before studying them with spaced repetition. Cards must follow the exact chronological progression of the textbook (page-by-page, derivation step-by-step) so the user can audit them in Anki's Browser/Preview without friction.
- **Target User / Execution Surface**: Solo student/engineer using Anki Desktop (Card Browser / Preview mode) side-by-side with a textbook PDF viewer on Windows. Synchronized via local AnkiConnect (`127.0.0.1:8765`).
- **Validated Architectural Core**:
  - **Zero Scheduler Hacking**: Never touch Anki's `due` integers, review queues, or deck options presets. Cards remain purely scheduled by Anki's SRS (FSRS/SM-2) once studied.
  - **Dedicated Note Types (`Textbook-Basic` / `Textbook-Cloze`)**: Independent clones of standard note types with an extra, non-rendered `Book_Order` field (`<chapter>.<section>.<page>.<seq>`, e.g., `04.01.089.02`). This unlocks 1-click deterministic sorting in Anki Browser without touching cards or templates in other decks.
  - **Narrative Traversal with 5-Pillar Lens**: The extraction agent sweeps each section page chronologically from top to bottom (preserving local context, derivations, and assumptions) while maintaining exhaustive 5-pillar coverage and the "Atomic Once" rule.

---

## 2. Core User Flows (The Happy Path)

### Flow 1: Chronological 5-Pillar Extraction (`flashcards/SKILL.md`)
1. `python book_tool.py prepare` renders 300-DPI page PNGs for the active chapter (e.g. Chapter 04).
2. For each section, the `SectionFlashcardExtractor` subagent performs:
   - **Pass 1 (Chronological Ground Sweep)**: Scans pages top-to-bottom in narrative sequence, extracting atomic definitions, equations, assumptions, and diagrams across the 5 Pillars right as they appear.
   - **Pass 2 (Synthesis Sweep)**: Attaches any high-level cross-page intuition or summary cards to the concluding milestone page.
3. Every card is assigned:
   - `id`: `ch04_s01_p089_c01`
   - `source_page`: `89`
   - `book_order`: `04.01.089.01`
   - Stored in `.cache/<book_slug>/ch_04/cards_4_1.json`.

### Flow 2: Note Type Resolution & Non-Destructive Anki Sync (`book_tool.py`)
1. `book_tool.py sync-anki` verifies if `Textbook-Basic` and `Textbook-Cloze` exist in Anki via AnkiConnect:
   - If missing, it auto-clones them from `Basic` and `Cloze`, adding the `Book_Order` field.
   - Standard `Basic` and `Cloze` note types used by other decks remain completely untouched.
2. In chapters configured for the new method (Chapters 4+), cards are assigned the `Textbook-*` models with `fields: {"Front": ..., "Back": ..., "Book_Order": "04.01.089.01"}` (or `Text`, `Back Extra`, `Book_Order`).
3. Existing cards are updated in-place via `updateNoteFields` without resetting intervals; new cards are added via `addNote`.

### Flow 3: Side-by-Side Reading Audit
1. The user opens the textbook PDF on one monitor and Anki's **Card Browser** on the other.
2. In Anki Browser, the user selects the target deck (e.g., `Textbooks::<Book>::Chapter 04` or subdeck `4.1`) and sorts by the `Book_Order` column.
3. The cards display in 100% perfect lockstep with the textbook text. As the user reads, they tap down-arrow to verify each card. If a card needs an edit or suspension, the user does it in Anki instantly.

---

## 3. System Architecture & Components

```
┌─────────────────────────────────────────────────────────────┐
│                 Textbook PDF Page Images                    │
│                 (300 DPI, Pages 89-94)                      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│          SectionFlashcardExtractor Subagent                 │
│  - Traversal: Chronological Top-to-Bottom                   │
│  - Lens: 5-Pillar Taxonomy (Definitions, Equations, ...)    │
│  - Guardrails: "Atomic Once" rule + 2-Pass Synthesis        │
│  - Output: cards_4_1.json with `book_order: 04.01.089.01`   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 book_tool.py Aggregator                     │
│  - Aggregates by section & book_order                       │
│  - Ensures `Textbook-Basic` & `Textbook-Cloze` exist in Anki │
│  - Maps fields: Front, Back, Book_Order                     │
│  - Syncs via AnkiConnect (addNote / updateNoteFields)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  Anki Desktop Collection                    │
│  - Isolated Note Types: Textbook-Basic & Textbook-Cloze     │
│  - Other decks untouched                                    │
│  - Card Browser: 1-click sort by `Book_Order` column        │
│  - Review Mode: Pure SRS (intervals uncompromised)          │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Data Model & Note Type Blueprint

### Anki Models

#### `Textbook-Basic` (Cloned from `Basic`)
- **Fields**:
  1. `Front` (Card question)
  2. `Back` (Card answer & explanations)
  3. `Book_Order` (Zero-rendered sequence string: `CC.SS.PPP.NN`)
- **Templates**:
  - Front: `{{Front}}`
  - Back: `{{FrontSide}}<hr id="answer">{{Back}}` *(Note: `{{Book_Order}}` is excluded from templates so it never displays during review mode)*.

#### `Textbook-Cloze` (Cloned from `Cloze`)
- **Fields**:
  1. `Text` (Cloze prompt with `{{c1::...}}`)
  2. `Back Extra` (Derivation intuition / media)
  3. `Book_Order` (Zero-rendered sequence string: `CC.SS.PPP.NN`)
- **Templates**:
  - Front: `{{cloze:Text}}`
  - Back: `{{cloze:Text}}<br>{{Back Extra}}`

### JSON Scratch Card Schema (`cards_X_Y.json`)
```json
{
  "section": "4.1",
  "section_title": "Frequency Domain Identification",
  "cards": [
    {
      "id": "ch04_s01_p089_c01",
      "book_order": "04.01.089.01",
      "source_page": 89,
      "seq": 1,
      "model": "Cloze",
      "pillar": "equations",
      "front": "The discrete-time Fourier transform (DTFT) of signal $s(t)$ is defined as {{c1::$\\Phi_s(\\omega) = \\sum_{\\tau=-\\infty}^{\\infty} R_s(\\tau) e^{-i\\omega \\tau}$}}.",
      "back": "Assuming wide-sense stationary noise with autocorrelation $R_s(\\tau)$.",
      "tags": ["dtft", "definitions", "pillar-equations"],
      "media": []
    }
  ]
}
```

---

## 5. Migration & Scope Boundary
- **Chapter Scoping**: This new ordering and model schema is enforced strictly for **Chapter 4 and Chapter 5** (and future chapters).
- **Backwards Compatibility**:
  - Chapters 1, 2, and 3 are **not** migrated or touched. Their existing notes and `Basic`/`Cloze` models in Anki remain active.
  - If the user explicitly runs `python book_tool.py refresh-cards --chapter 1` in the future, it can optionally be re-synthesized into the new format.

---

## 6. Implementation Checklist
- [ ] **Task 1: Extractor Prompt (`flashcards/SKILL.md`)**:
  - Update instructions to mandate chronological top-to-bottom reading traversal per page.
  - Add "Atomic Once" rule and Pass 1 / Pass 2 synthesis guidance.
  - Add `book_order` (`<ch>.<sec>.<page>.<seq>`) and `source_page` to the output schema.
- [ ] **Task 2: Model Provisioning & Field Mapping (`book_tool.py`)**:
  - In `sync_chapter_to_anki`, check if `Textbook-Basic` and `Textbook-Cloze` exist in Anki; create them via `createModel` if absent.
  - When processing chapters $\ge 4$, map notes to `Textbook-Basic` and `Textbook-Cloze` and populate `Book_Order`.
  - For chapters $< 4$, retain existing behavior unless forced.
- [ ] **Task 3: Ledger & Aggregation Updates (`book_tool.py`)**:
  - Store and preserve `book_order` and `source_page` in `decks/<book_slug>/ch_<XX>_cards.json`.
