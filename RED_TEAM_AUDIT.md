# Red-Team Architectural Audit Log: Book-Synthesizer AnkiConnect Integration

- **Date**: 2026-10-20
- **Companion Spec**: [TECH_SPEC.md](./TECH_SPEC.md)

---

## 1. Executive Summary
The user requested adding automated **Anki flashcard generation and sync** to the existing textbook synthesizer workflow, specifically using **AnkiConnect** so cards can be iteratively added, updated, and refined without wiping review history.

The 🔴 Red Team audited the initial design, uncovering 4 key failure modes:
1. Two-way distributed state inconsistency if user cards were stored loosely.
2. Anki note model mutation crashes (`Basic` $\leftrightarrow$ `Cloze` cannot be updated in-place via `updateNoteFields`).
3. SQLite database locking and file race conditions caused by parallel section subagents calling AnkiConnect concurrently.
4. Review queue clutter from orphaned cards upon chapter re-synthesis.

Following a 2-round debate and the user's executive rulings in the Cross-Examination Chamber, the architecture was solidified around **strict separation of concerns** (clean notes in Obsidian, flashcards in Anki) with single-threaded safe synchronization, non-destructive auto-suspension for orphaned cards, and independent card refresh without full chapter re-synthesis.

---

## 2. Concessions & Adopted Improvements

| Area / Component | Initial Proposal | Red Team Critique | Adopted Solution |
| :--- | :--- | :--- | :--- |
| **Concurrency & Sync Timing** | Subagents push cards directly to AnkiConnect. | Concurrent subagent HTTP calls cause Windows file-lock errors and Anki SQLite `"database is locked"` errors. | **Single-Threaded Finalize**: Subagents write section cards to isolated `.cache/ch_XX/cards_X_Y.json` files; single-threaded `finalize` step merges and pushes to AnkiConnect sequentially. |
| **Note Model Mutation** | In-place updates via `updateNoteFields` regardless of card type. | AnkiConnect throws an exception if trying to update fields across different models (`Basic` vs `Cloze`). | **Model Replacement Protocol**: If model changes, the engine creates the new note and suspends/retires the old note. |
| **MathJax Translation** | Global regex replace of `$` with `\(` and `$$` with `\[`. | Breaks escaped literal dollars (`\$`), inline code blocks, and LaTeX tabular environments. | **Token-Aware Math Parser**: Converts math blocks while respecting code blocks and escaped characters. |
| **Orphan Management** | Untracked or passive tagging. | Re-synthesizing chapters pollutes the user's active review queue with ghost cards. | **Auto-Suspension**: Replaced/superseded cards are tagged `book_synthesizer::orphaned` and auto-suspended in Anki; optional `--prune` flag for hard deletion. |
| **Card Refresh Granularity** | Full chapter re-synthesis required to refresh cards. | High compute overhead and risk of re-writing finalized Obsidian reading notes just to tweak flashcards. | **Decoupled Refresh**: Added `refresh-cards` subcommand that reads existing Obsidian primer notes and extracts/updates cards without re-running PDF extraction. |

---

## 3. Defended Decisions

- **Local JSON Deck Ledger (`vault/decks/ch_XX_cards.json`)**:
  - *Challenged by Red Team*: Red argued that querying Anki directly via `findNotes` eliminates the local file.
  - *Defended Rationale*: AnkiConnect is only available when Anki desktop is open on localhost. If the user synthesizes a chapter offline or with Anki closed, an Anki-only query completely halts synthesis. The local ledger acts as a safe, offline-first staging queue.
- **No Automatic Hard Deletions**:
  - *Challenged by Red Team*: Red warned about accumulating ghost cards.
  - *Defended Rationale*: In spaced repetition, losing card IDs destroys months of calculated intervals, stability, and ease factors. Auto-suspension protects user investment while keeping daily reviews clean.

---

## 4. Cross-Examination & User Executive Rulings

### Fork 1: Flashcard Storage Location (JSON Ledger vs. Markdown Deck in Vault)
- **🔵 Blue Team Stance**: Keep flashcards in a dedicated JSON ledger (`vault/decks/ch_XX_cards.json`). Keep reading notes in Obsidian 100% clean and distraction-free.
- **🔴 Red Team Stance**: Store flashcards in a human-readable `Flashcards - Chapter XX.md` markdown file in Obsidian.
- **⚖️ Final User Ruling**: **Blue's approach adopted**. *"Let's keep things separated: notes in Obsidian, flashcards in Anki."*

### Fork 2: Orphaned Card Management (Silent Auto-Suspension vs. Interactive CLI Pruning)
- **🔵 Blue Team Stance**: Automatically suspend superseded cards in Anki and add the tag `book_synthesizer::orphaned`. No interruptions, no permanent deletion.
- **🔴 Red Team Stance**: Interactively prompt the user in terminal during sync: `[K]eep, [S]uspend, [D]elete`.
- **⚖️ Final User Ruling**: **Blue's approach adopted**. Re-running synthesis on the same chapter will be rare; auto-suspension removes unwanted cards from daily reviews while allowing manual re-insertion in Anki if the user liked a specific card. Furthermore, the user requested the ability to refresh flashcards without having to re-synthesize the whole chapter.

---

## 5. Discard Pile (Rejected Alternatives)

- **Embedding Flashcard Blocks inside Section Reading Notes**: Rejected to protect Obsidian notes as pure pre-reading primers without Q&A clutter.
- **Direct Multi-threaded Calls to AnkiConnect**: Rejected due to SQLite database concurrency lockups.
- **Silent Automated Note Deletion in Anki**: Rejected to prevent accidental loss of user review intervals and learning history.
- **Interactive Blocking Terminal Prompts for Sync**: Rejected in favor of smooth, non-blocking auto-suspension.
