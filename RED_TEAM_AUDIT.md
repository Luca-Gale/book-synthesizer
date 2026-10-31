# Red-Team Architectural Audit Log: Deterministic Chronological Flashcards

- **Date**: 2026-10-30
- **Companion Spec**: [TECH_SPEC.md](./TECH_SPEC.md)

---

## 1. Executive Summary
The user requested a workflow change: during the initial reading of a textbook chapter, they keep Anki side-by-side to perform real-time verification and sanity checks on generated flashcards before studying them with spaced repetition. They asked how difficult it would be to enforce the card order in Anki to match the book concepts perfectly.

The initial Blue Team draft attempted to enforce this via Anki's scheduler internals (`due` integers, deck options presets, and AnkiConnect `reposition` calls). 
The Red Team exposed that hacking Anki's scheduler was brittle, over-engineered, and prone to breaking as soon as cards were reviewed or refreshed. 

Through the debate and user cross-examination, both teams aligned on a clean, robust data architecture: **leave Anki's scheduler 100% untouched**, provision isolated **`Textbook-Basic` and `Textbook-Cloze`** note types with an unrendered `Book_Order` field (`04.01.089.02`), and adapt the extraction agent to a **narrative top-to-bottom traversal** anchored by the 5-Pillar lens. The user explicitly scoped this rollout to Chapters 4 and 5 onward, preserving earlier chapters untouched.

---

## 2. Concessions & Adopted Improvements

| Area / Component | Initial v1 Proposal (Blue) | Red Team Critique | Adopted Solution |
| :--- | :--- | :--- | :--- |
| **Anki Queue Ordering** | Modify card `due` integers via AnkiConnect `reposition` and set deck gather order presets. | Over-engineering. In Anki, `due` is SRS scheduling state; FSRS/SM-2 overwrites it once studied, destroying the linear order in Browser. | **Zero scheduler hacking.** Cards schedule naturally. Linear order is maintained via an explicit metadata field. |
| **Browser Sortability** | Store `source_page` and `seq` only in JSON scratch files/ledger. | Anki's Card Browser cannot sort on JSON files. It only sorts on first-class Note Fields. | Add an explicit `Book_Order` field (`CC.SS.PPP.NN`) to the note model so Anki Browser can sort by it with 1 click. |
| **Note Type Safety** | Inject fields directly or add tags into existing standard `Basic` / `Cloze`. | Mutating global `Basic`/`Cloze` note types pollutes other decks (languages, medical, programming). | Auto-clone dedicated `Textbook-Basic` and `Textbook-Cloze` models, leaving personal decks 100% untouched. |

---

## 3. Defended Decisions

- **Anki Browser as the Primary Audit Surface**: 
  - *Challenge*: The Red Team proposed bypassing Anki entirely for reading audits by appending an Obsidian card table to the bottom of the section primer notes.
  - *Defense*: The user's goal is real-time sanity checking where bad cards or clozes can be edited or suspended immediately. Anki Browser/Preview allows inline editing and immediate suspension. An Obsidian table would require complex bi-directional sync to push edits back to Anki.

---

## 4. Cross-Examination & User Executive Rulings

### Fork 1: Global Template Mutation vs. Isolated Note Types
- **🔵 Blue Team Stance**: Dedicated note types (`Textbook-Basic`/`Cloze`) give a clean `Book_Order` column in Anki Browser without touching standard templates, and remain invisible during reviews.
- **🔴 Red Team Stance**: Warned against creating profile sprawl unless guaranteed that existing note types remain unaffected.
- **Key Insights from Cross-Examination**: The user inquired if introducing new note types would preserve their existing card templates in other decks without modification. Blue confirmed that note types in Anki are completely isolated blueprints.
- **⚖️ Final User Ruling**: Approved dedicated `Textbook-Basic` and `Textbook-Cloze` note types.

### Fork 2: Impact on Extraction Quality (5 Pillars vs. Chronological)
- **User Inquiry**: Does shifting to chronological extraction degrade card quality or abandon the 5 Pillars philosophy?
- **Blue Team Explanation**: The 5 Pillars is a *coverage checklist*, while chronology is a *traversal strategy*. Shifting to top-to-bottom reading improves local context grounding (equations stay beside their assumptions) without sacrificing depth. Guardrails ("Atomic Once" rule + 2-pass synthesis) prevent greedy duplication.
- **⚖️ Final User Ruling**: Approved narrative traversal with the 5-Pillar lens.

### Fork 3: Chapter Rollout Scope
- **⚖️ Final User Ruling**: Enforce this new method specifically for **Chapters 4 and 5** (and future chapters). Do not alter Chapters 1, 2, or 3.

---

## 5. Deferred Ideas & Discard Pile

- **AnkiConnect `reposition` queue calls**: Discarded. Using `due` integer manipulation for document pagination creates conflicts with Anki's SRS scheduling.
- **Visible In-Card Reading Headers**: Discarded. Displaying page numbers or sequence IDs on the front of cards creates artificial retrieval clues that ruin long-term active recall during reviews.
- **Obsidian-Only Card Audit Table**: Discarded as primary surface. Kept Anki Card Browser as the primary interactive audit surface for immediate editing/suspension.
