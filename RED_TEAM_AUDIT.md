# Red-Team Architectural Audit Log: Book-Synthesizer

- **Date**: 2026-10-20
- **Companion Spec**: [TECH_SPEC.md](./TECH_SPEC.md)

---

## 1. Executive Summary
`book-synthesizer` began in Phase 1 as a standalone Python CLI that would call the external Google Gemini Cloud API (`google-genai`), store state in a local SQLite database (`state.db`), parse Pydantic JSON schemas, and emit 50+ micro-notes per chapter (one for every 5-line typographical block of text) using `Jinja2` templates.

Through two rounds of adversarial Red-Teaming and the **Cross-Examination Chamber**, three transformative breakthroughs reshaped the architecture into a dramatically simpler, faster, $0-API-cost system:
1. **Antigravity-Native Inversion of Control**: The user operates exclusively inside Antigravity without an external Gemini API key. We inverted the architecture so **Antigravity + parallel subagents act as the multimodal vision/math engine**, invoking a lightweight local Python CLI (`book_tool.py`) for deterministic PDF page rendering, figure cropping, and Obsidian vault linking.
2. **True "Paragraph" Granularity (`1.1`, `1.2`, ..., `1.5`)**: Cross-examination clarified that "paragraph" (*paragrafo*) refers to the **numbered sections of a chapter** (e.g., `1.1 Dynamic Systems`, `1.2 Models`, `1.3 ARX Models...`, skipping `1.6 Bibliography`), NOT 5-line typographical blocks. This reduced note count from ~60 micro-notes per chapter to **5–10 deep, cohesive Section Primer Notes (`X.Y`) per chapter**, eliminating output token cliffs and JSON escaping bugs entirely.
3. **Zero-Friction Drop Folder + `chapter.txt` Input**: Instead of typing long file paths and page range flags in a CLI, the user simply drops their active textbook PDF into `book/`, writes the target chapter number in `chapter.txt`, and tells Antigravity to synthesize.

---

## 2. Concessions & Adopted Improvements
Architectural changes proposed by the 🔴 Red Team that the 🔵 Blue Team accepted during Rounds 1 & 2:

| Area / Component | Initial v1 Proposal (Blue) | Red Team Critique | Adopted Solution |
| :--- | :--- | :--- | :--- |
| **State Storage & Templating** | Local `sqlite3` database (`SynthesisJob`, `ParagraphPrimer` tables) + `Jinja2` templates. | Over-engineered for a local chapter-by-chapter tool; SQLite hides cached payloads inside binary tables. | Flat human-readable filesystem cache (`.cache/ch_X/manifest.json` + page PNGs) and native Python Markdown formatting. |
| **LLM Output Protocol for Heavy LaTeX** | Pydantic Structured JSON (`response_schema`). | LaTeX macros (`\nabla`, `\rho`, `\tau`, `\frac`, `\beta`) collide with JSON control characters (`\n`, `\r`, `\t`, `\f`, `\b`), silently corrupting equations. | Direct Markdown writing by Antigravity section subagents (zero JSON wrapping around LaTeX). |
| **Context Window & Output Token Budget** | Single monolithic pass over an entire chapter range. | Causes "lazy summarization degradation" and output token truncation after a few pages. | **1 Subagent per Numbered Section (`X.Y`)**: Each 2–6 page section gets a dedicated pass with full token budget. |
| **Obsidian Re-Run Safety** | Blindly overwrite `.md` files on re-run. | Destroys personal annotations added by the user in Obsidian after initial synthesis. | Protected `<!-- USER NOTES BELOW THIS LINE -->` divider; `book_tool.py finalize` preserves user content below the marker. |
| **Figure Cropping Safety** | Raw bounding-box crop (`[ymin, xmin, ymax, xmax]`). | Tight bounding boxes often clip plot axis labels or multi-panel captions (`(a)`, `(b)`). | Added a 5% safety padding margin in `book_tool.py crop` on 300-DPI rendered page PNGs. |

---

## 3. Defended Decisions
Challenges raised by the 🔴 Red Team that were successfully defended and kept:

- **Vision-Based 2D Bounding Box Cropping on 300-DPI Page Renders (`PyMuPDF` + `Pillow`)**:
  - *Why challenged*: Red Team questioned whether native PDF image extraction (`page.get_images()`) could replace vision bounding boxes.
  - *Why preserved*: Engineering textbooks (like Ljung's *System Identification*) draw block diagrams, signal flow graphs, and plots using PDF vector paths and floating LaTeX font glyphs rather than embedded JPEGs. Rendering the page at 300 DPI and cropping `[ymin, xmin, ymax, xmax]` with a 5% margin is the only way to reliably capture vector diagrams and their mathematical labels intact.

---

## 4. Cross-Examination & User Executive Rulings
Key architectural pivots resolved in the **Cross-Examination Chamber**:

### Pivot 1: External Cloud API Key vs. Antigravity-Native Execution
- **User Revelation**: *"I don't have a Gemini API, I only use Antigravity."*
- **Architectural Resolution**: Dropped `google-genai` SDK and external API keys completely. Designed a hybrid pipeline where `book_tool.py` handles local PDF-to-PNG rendering, figure cropping, and Obsidian linking, while Antigravity's multimodal `read_file` and `invoke_subagent` tools perform the visual reading and mathematical synthesis at zero API cost.

### Pivot 2: Definition of "Paragraph" (`X.Y` Numbered Sections) & Sub-Subsections (`X.Y.Z`)
- **User Clarification & Screenshot**: Provided a screenshot of Chapter 1 of Ljung's *System Identification* (`1.1 Dynamic Systems`, `1.2 Models`, `1.3 An Archetypical Problem—ARX Models...`, `1.4 The System Identification Procedure`, `1.5 Organization of the Book`, `1.6 Bibliography`), clarifying that each dedicated Obsidian note corresponds to a numbered section `1.1`, `1.2`, ..., `1.5` (ignoring `1.6 Bibliography`).
- **⚖️ Final User Ruling**:
  1. **1 `.md` File per `X.Y` Section**: Keep `X.Y` as the dedicated Obsidian file level, and render deeper sub-subsections (`X.Y.1`, `X.Y.2`) as `##` / `###` headings inside that note.
  2. **Automatic Non-Content Filtering**: Automatically skip `Bibliography`, `References`, `Problems`, and `Exercises` sections.

### Pivot 3: Verbatim Source Callout & Input Ergonomics
- **⚖️ Final User Ruling**:
  1. **Ditch Verbatim Source Reference Completely**: Do not bloat the Obsidian note with verbatim copied text or embedded source PDFs—keep the note 100% focused as a pre-reading primer; the user will read the actual textbook section afterward.
  2. **Drop-Folder (`book/`) + `chapter.txt` Workflow**: Instead of passing CLI file paths and page numbers on every run, the tool watches a dedicated `book/` folder where the user drops their PDF and reads a simple `chapter.txt` file containing the chapter number to synthesize.

---

## 5. Deferred Ideas & Discard Pile
Features, abstractions, or technologies explicitly rejected during red-teaming (do not re-introduce):

- **External `google-genai` / `openai` / `anthropic` SDK Clients**: Rejected because the user runs exclusively inside Antigravity without external API keys.
- **SQLite State Database (`state.db`) & `Jinja2` Templates**: Rejected as unnecessary boilerplate compared to `.cache/ch_X/manifest.json` and native Python Markdown formatting.
- **Pydantic JSON Output Wrapping for Math Notes**: Rejected to avoid JSON control-character collisions (`\nabla` $\to$ `\n`, `\frac` $\to$ `\f`, `\tau` $\to$ `\t`, `\rho` $\to$ `\r`, `\beta` $\to$ `\b`).
- **Collapsible Verbatim Source Text Callouts**: Explicitly rejected by user ruling to keep notes lean and focused strictly on intuition, mathematical rigor, and pre-reading guidance.
- **5-Line Typographical Paragraph Chunking**: Replaced by `X.Y` numbered section notes (`1.1`, `1.2`, etc.).
