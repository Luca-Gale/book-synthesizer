# Technical Specification: Book-Synthesizer

- **Status**: `FINAL — Red-Team Validated`
- **Last Updated**: 2026-10-20
- **Companion Audit Log**: [RED_TEAM_AUDIT.md](./RED_TEAM_AUDIT.md)

---

## 1. Overview & Core Problem
- **Problem Statement**: Dense engineering and mathematics textbooks (e.g., Ljung's *System Identification*, fluid mechanics, control theory) pack heavy conceptual leaps, implicit assumptions, and multi-step derivations into each numbered section (`1.1`, `1.2`, `1.3`). Standard AI summarizers strip away mathematical rigor, while raw OCR tools dump unguided text. The user needs a zero-friction, **Antigravity-native tool** that takes a dropped textbook PDF and a target chapter number, and generates a dedicated Obsidian **Pre-Reading Primer Note** for each numbered section (`X.1`, `X.2`, ...) preserving both physical/conceptual intuition and complete mathematical rigor (LaTeX + cropped textbook figures).
- **Target User / Execution Surface**: Solo engineer/student operating inside **Antigravity** (zero external LLM API keys required), combining a local Python PDF/Vault CLI helper (`book_tool.py`) with Antigravity's native multimodal vision and parallel subagents.
- **Non-Goals (Out of Scope for v1)**:
  - External paid LLM API integrations (`OPENAI_API_KEY`, `GEMINI_API_KEY` SDK loops).
  - Splitting notes down to 5-line typographical text blocks (granularity is strictly 1 `.md` note per numbered section `X.Y`, with `X.Y.Z` kept as internal `##`/`###` headings).
  - Dumping verbatim source text or redundant full-page copies at the bottom of notes (the user reads the physical/PDF textbook after reading the Obsidian primer).
  - Synthesizing non-content sections (*Bibliography*, *References*, *Problems*, *Exercises*, *Appendices*).

---

## 2. Core User Flows (The Happy Path)

1. **Flow 1 — Zero-Friction Drop & Chapter Selection**:
   - User drags and drops their active textbook PDF into the workspace `book/` folder (e.g., `book/ljung_system_identification.pdf`).
   - User opens `chapter.txt` in the workspace root and types a single number (e.g., `1` for Chapter 1).
   - User tells Antigravity in chat: *"Synthesize chapter"* (or triggers the workspace skill).
2. **Flow 2 — Automated Section Slicing & Page Rendering (`book_tool.py prepare`)**:
   - Antigravity runs `python book_tool.py prepare`.
   - The script auto-detects the PDF in `book/` and reads the target chapter number `X` from `chapter.txt`.
   - It parses the PDF's Table of Contents (or renders the ToC pages if bookmarks are absent) to locate Chapter `X` and all its numbered sections (`X.1`, `X.2`, ..., `X.k`) with their start/end page numbers, automatically filtering out *Bibliography / References / Problems / Exercises*.
   - It renders 300-DPI PNG images of the chapter's pages into `.cache/ch_X/pages/` and writes `.cache/ch_X/manifest.json`.
3. **Flow 3 — Multimodal Section Synthesis & Figure Cropping (Antigravity + Subagents)**:
   - For each numbered section `X.Y` in `manifest.json`, Antigravity (or parallel `self` subagents spawned per section) reads the 300-DPI page PNGs for that section using `read_file`.
   - When a section contains relevant diagrams, plots, or block schematics, the agent invokes:
     `python book_tool.py crop --page <P> --bbox <ymin,xmin,ymax,xmax> --out "<vault>/assets/fig_X_Y_1.png"`
     which crops the 300-DPI page image with a 5% safety padding margin so axis labels and captions are never clipped.
   - The agent writes the dedicated Obsidian note `<vault>/Chapter X/X.Y <Section Title>.md` directly in clean Markdown + MathJax.
4. **Flow 4 — Vault Linking, MathJax Validation & MOC Generation (`book_tool.py finalize`)**:
   - Antigravity runs `python book_tool.py finalize`.
   - The script generates/updates `<vault>/Chapter X/00_MOC_Chapter_X.md` (Map of Content) linking all `X.1` ... `X.k` section notes in order, injects sequential `← [[Prev]] | [[MOC]] | [[Next]] →` navigation headers, validates MathJax `$` / `$$` delimiters, and preserves any content below `<!-- USER NOTES BELOW THIS LINE -->` on re-runs.

---

## 3. System Architecture & Components

- **High-Level Architecture**:
  ```mermaid
  flowchart TD
      subgraph UserInput ["1. Zero-Friction Input"]
          Drop["book/*.pdf (Drag & Drop)"]
          ChFile["chapter.txt (e.g. '1')"]
      end

      subgraph Prep ["2. Local Python Toolkit (book_tool.py)"]
          Prepare["book_tool.py prepare (PyMuPDF)"]
          Crop["book_tool.py crop (Pillow + 5% Pad)"]
          Finalize["book_tool.py finalize (Linker + MathJax Check)"]
      end

      subgraph Agent ["3. Antigravity Multimodal Engine (No API Key)"]
          Orchestrator["Main Agent (Reads manifest.json)"]
          Subagents["Parallel Section Subagents (1 per Section X.Y)"]
      end

      subgraph Output ["4. Obsidian Output Vault"]
          Vault[("vault/Chapter X/\n- 00_MOC_Chapter_X.md\n- X.1 Section.md\n- X.2 Section.md\n- assets/fig_*.png")]
      end

      Drop --> Prepare
      ChFile --> Prepare
      Prepare -->|".cache/ch_X/manifest.json + 300-DPI PNGs"| Orchestrator
      Orchestrator --> Subagents
      Subagents -->|"ymin,xmin,ymax,xmax"| Crop
      Crop --> Vault
      Subagents -->|"Direct Markdown + LaTeX"| Vault
      Vault --> Finalize
  ```

- **Tech Stack**:
  - **Language / Runtime**: Python 3.11+
  - **PDF & Image Processing**: `PyMuPDF` (`fitz`) for ToC inspection and 300-DPI page rendering + `Pillow` for padded bounding-box figure cropping
  - **Multimodal AI Engine**: **Antigravity Native** (`read_file` vision on 300-DPI page PNGs + `invoke_subagent` for parallel section synthesis) + Workspace Skill (`.agent/skills/synthesize-chapter/SKILL.md`)
  - **State & Caching**: Flat filesystem cache under `.cache/ch_<X>/` (`manifest.json` + rendered page PNGs)
  - **Output Target**: Local Obsidian vault folder (`vault/` by default, or configurable path in `config.json`)

---

## 4. Data Model & Note Structure

### 4.1 Directory Layout
```text
book-synthesizer/
├── book/                        # Drag-and-drop textbook PDF here (keeps 1 active PDF)
├── chapter.txt                  # Contains simply the target chapter number, e.g.: 1
├── config.json                  # Optional settings (vault_path, dpi, skip_keywords)
├── book_tool.py                 # Local CLI helper (prepare, crop, finalize)
├── .agent/skills/synthesize/    # Antigravity skill orchestrating the end-to-end flow
│   └── SKILL.md
├── .cache/                      # Rendered 300-DPI page PNGs & manifest.json per chapter
└── vault/                       # Default Obsidian vault output (or external vault path)
    ├── assets/
    │   └── ch01/
    │       └── fig_1_3_arx.png
    └── Chapter 01 - Introduction/
        ├── 00 - Chapter 1 MOC.md
        ├── 1.1 Dynamic Systems.md
        ├── 1.2 Models.md
        ├── 1.3 An Archetypical Problem - ARX Models and Linear Least Squares.md
        ├── 1.4 The System Identification Procedure.md
        └── 1.5 Organization of the Book.md
```

### 4.2 Dedicated Section Note Template (`X.Y <Title>.md`)
Each numbered section note strictly follows this pedagogical primer layout:
1. **YAML Frontmatter**: `chapter`, `section`, `pages`, `tags: [primer, chapter-X]`.
2. **Navigation Bar**: `← [[X.Y-1 Prev]] | [[00 - Chapter X MOC]] | [[X.Y+1 Next]] →`
3. **`## 1. Core Intuition & Motivation`**:
   - Why does this section exist in the chapter's arc?
   - What physical/engineering phenomenon or modeling problem is being addressed in plain, vivid language?
4. **`## 2. Mathematical Rigor & Derivations`**:
   - Organized with `### X.Y.1 ...` subheadings if the section contains sub-subsections.
   - Every equation preserved in strict Obsidian MathJax (`$...$` and `$$...$$`).
   - **Symbol & Variable Glossary Table**: Explicit definition, dimensions/units, and mathematical space (e.g., $\theta \in \mathbb{R}^d$) for every symbol introduced.
   - **Step-by-Step Derivation Logic**: Unpacks the algebraic or calculus steps the textbook authors do "in their head" between numbered equations, explicitly stating all assumptions (linearity, time-invariance, noise assumptions, boundary conditions).
   - **Inline Visual Walkthroughs & Diagrams**: Cropped textbook figures (`![[assets/fig_X_Y_slug.png]]`) are embedded **directly inline** within the exact paragraph, derivation, or case study they illustrate, accompanied immediately by a *How to Read This Diagram* breakdown of axes, signal flows, and geometric meaning.
5. **`## 3. Pre-Reading Compass (What to Watch Out For)`**:
   - Bullet list of the 2–3 hardest conceptual leaps or subtle notation pitfalls in this section so the reader is primed *before* reading the original textbook pages.
6. **Protected User Annotation Zone**:
   - `<!-- USER NOTES BELOW THIS LINE -->` (everything below this marker is preserved untouched across re-runs).

---

## 5. Constraints, Edge Cases & Failure Modes
- **Missing or Incomplete PDF Bookmarks (ToC)**:
  - Many scanned or older engineering PDFs only have Chapter-level PDF bookmarks (e.g., `Chapter 1`, `Chapter 2`) without `1.1`, `1.2` bookmarks, or lack PDF bookmarks entirely.
  - **Fallback Strategy**: `book_tool.py prepare` checks `doc.get_toc()`. If section-level `X.Y` bookmarks are missing, `book_tool.py render-pages` renders the Chapter `X` pages (or ToC pages), allowing Antigravity to visually read the chapter's opening outline (just like the screenshot of Chapter 1 in Ljung) and pass the exact `X.Y` section page ranges to `manifest.json`.
- **Skipped Sections Filter**:
  - Automatically skips any section matching case-insensitive keywords: `bibliography`, `references`, `problems`, `exercises`, `further reading`, `historical notes`, `appendix`.
- **MathJax Sanitization**:
  - `book_tool.py finalize` scans generated `.md` files to fix common Obsidian MathJax rendering issues (e.g., stripping illegal spaces immediately inside `$ x $` $\to$ `$x$`, ensuring blank lines around `$$...$$` display blocks).
- **Filename Sanitization**:
  - Replaces em-dashes (`—`), colons (`:`), slashes (`/`), and question marks in section titles with clean hyphens (` - `) so filenames are 100% compatible with Windows and Obsidian wikilinks.

---

## 6. Implementation Roadmap (v1 Milestones)
- [ ] **Milestone 1 — Workspace Scaffolding & `book_tool.py` Core**:
  - Create `book/`, `chapter.txt`, `config.json`, and `book_tool.py` (`prepare`, `render-pages`, `crop`, `finalize` subcommands using `PyMuPDF` and `Pillow`).
- [ ] **Milestone 2 — MathJax Validator, Non-Destructive Merger & MOC Generator**:
  - Implement automatic `[[Prev]]`/`[[Next]]`/`[[MOC]]` link injection, MathJax formatting checks, and `<!-- USER NOTES BELOW THIS LINE -->` preservation in `book_tool.py finalize`.
- [ ] **Milestone 3 — Antigravity Skill (`.agent/skills/synthesize/SKILL.md`) & End-to-End Verification**:
  - Create the workspace skill that orchestrates `book_tool.py` + parallel section subagents, and test it end-to-end on Chapter 1 of your textbook.
