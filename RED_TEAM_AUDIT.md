# Red-Team Architectural Audit Log: Decoupled Book-Synthesizer & Exhaustive Flashcard Engine

- **Date**: 2026-10-22
- **Companion Spec**: [TECH_SPEC.md](./TECH_SPEC.md)

---

## 1. Executive Summary
The architecture evolved from a single monolithic `/synthesize` skill—where one section subagent wrote both the Obsidian Pre-Reading Primer note and the Anki flashcards simultaneously—into a **strictly decoupled two-agent pipeline**:
1. **`SectionNoteSynthesizer` ([`.agent/skills/synthesize/SKILL.md`](./.agent/skills/synthesize/SKILL.md))**: Dedicated exclusively to pedagogical narrative, step-by-step mathematical derivations, symbol glossaries, and cropping textbook diagrams.
2. **`SectionFlashcardExtractor` ([`.agent/skills/flashcards/SKILL.md`](./.agent/skills/flashcards/SKILL.md))**: Dedicated exclusively to exhaustive, atomic active-recall extraction directly from the 300-DPI textbook page PNGs, governed by a 5-Pillar Extraction Taxonomy and backed by a shared cropped-figure asset manifest.

This separation allows the user to fine-tune flashcard generation rules, density, and phrasing independently without risking regressions in Obsidian note synthesis (and vice versa), while ensuring flashcards extract 100% of the source textbook's notions rather than summarizing an already-condensed note.

---

## 2. Concessions & Adopted Improvements
Architectural changes proposed by the 🔴 Red Team that the 🔵 Blue Team accepted during Rounds 1 & 2:

| Area / Component | Initial v1 Proposal (Blue) | Red Team Critique | Adopted Solution |
| :--- | :--- | :--- | :--- |
| **Diagram & Figure Sharing (`assets_manifest.json`)** | `SectionNoteSynthesizer` crops figures into `vault/.../assets/`, while `SectionFlashcardExtractor` runs isolated on raw PDF pages. | **The "Orphan Crop" Dilemma**: If the Flashcard Agent runs decoupled on raw pages, it either lacks access to cropped diagram filenames or duplicates cropping work with conflicting filenames. | `book_tool.py crop` automatically records every cropped figure into `.cache/<book>/ch_XX/assets_manifest.json`, and `refresh-cards` exposes `section_assets` alongside `page_pngs`. `SectionFlashcardExtractor` reuses existing crops and has fallback `crop` access if an uncropped figure is needed. |
| **Exhaustive Extraction vs. Anki Bloat** | Unbounded prompt instruction: *"Extract literally everything from the section; over-generation is welcomed."* | **The Anki Bloat & Suspension Fatigue Trap**: Unbounded LLM extraction produces trivial semantic fluff and multi-clause cards, forcing exhausting manual suspension in Anki. | Adopted the **5-Pillar Flashcard Extraction Taxonomy** (1. Formal Definitions, 2. Governing Equations/Derivations, 3. Explicit/Implicit Assumptions, 4. Physical/Geometric Intuition, 5. Diagram Interpretation) + strict **Minimum Information Principle** (1 atomic fact per card). |
| **Independent Note Re-Finalization (`--notes-only`)** | `book_tool.py finalize` always triggered both Obsidian MOC generation and AnkiConnect deck syncing. | Tuning the note synthesizer alone would still trigger Anki aggregation and syncing. | Added `--notes-only` flag to `book_tool.py finalize` so Obsidian notes and MOC links can be rebuilt completely independently of Anki. |

---

## 3. Defended Decisions
Challenges raised by the 🔴 Red Team that were successfully defended and kept as originally designed:

- **Direct-from-PDF Multimodal Reading by `SectionFlashcardExtractor`**:
  - *Challenge*: Red Team argued that having both `SectionNoteSynthesizer` and `SectionFlashcardExtractor` read the 300-DPI page PNGs incurs a "Double Vision" token cost and could risk terminology drift compared to reading the synthesized Markdown note.
  - *Defense*: The user's long-term study workflow relies almost exclusively on Anki flashcards after the initial chapter reading, making flashcards the #1 priority artifact. Feeding the Obsidian note as the primary source would turn flashcards into a lossy summary of a summary. Reading the 300-DPI textbook pages directly guarantees zero omitted equations, sidebars, or subtle assumptions, while verbatim textbook nomenclature prevents drift.

---

## 4. Cross-Examination & User Executive Rulings
Deadlocks that went to the **Cross-Examination Chamber** and how the user ruled:

### Fork 1: Pipeline Coordination Between Note Synthesis and Flashcard Extraction
- **🔵 Blue Team Stance (Pipelined Handoff)**: During a full `/synthesize` run, `SectionNoteSynthesizer` runs first (writing the note and cropping figures into `vault/.../assets/`), followed immediately by `SectionFlashcardExtractor` (which reads the raw PDF pages and embeds the already-cropped figures). Subsequent flashcard fine-tuning runs `SectionFlashcardExtractor` standalone via `/flashcards`.
- **🔴 Red Team Stance (Standalone Parallel Workers)**: Decouple figure cropping into a separate daemon/pre-pass so flashcards could be generated for a new chapter before—or without ever—generating Obsidian primer notes.
- **Key Insights from Cross-Examination**: The user pointed out that their real-world study sequence is strictly `Obsidian Priming Notes -> Textbook Deep Dive -> Long-Term Anki Reviews`. Since flashcards are never needed *before* the priming notes exist on initial synthesis, Red Team's concern about waiting for notes on initial run does not apply in practice.
- **⚖️ Final User Ruling**: **Approach 1 (Pipelined Handoff with Shared Asset Manifest & Standalone `/flashcards` Re-Run)**. Both teams aligned on this ruling.

---

## 5. Deferred Ideas & Discard Pile
Features, abstractions, or technologies explicitly rejected during red-teaming (so future development sessions do not accidentally re-introduce them):

- **Note-Only Flashcard Extraction (Summarizing the Markdown Primer)**: Rejected because it degrades flashcard completeness and violates the requirement that nothing in the textbook should feel new after studying the deck.
- **Separate Pre-Pass Figure Detection Agent**: Rejected as premature complexity given that `SectionNoteSynthesizer` already inspects every page prior to `SectionFlashcardExtractor` during initial chapter synthesis, and `SectionFlashcardExtractor` retains fallback `book_tool.py crop` capability.
