# Book-Synthesizer

An **Antigravity-native** workflow and local Python toolkit that transforms dense engineering and mathematics textbooks into section-by-section (`1.1`, `1.2`, ...) **Obsidian Pre-Reading Primer Notes**—preserving physical intuition, complete mathematical rigor (LaTeX/MathJax), and cropped textbook figures.

---

## Quick Start (3 Steps)

1. **Drop your textbook PDF** into the [`book/`](./book/) folder.
2. **Type the chapter number** you want to study (e.g., `1`) into [`chapter.txt`](./chapter.txt).
3. **Tell Antigravity in chat**:
   > `Synthesize the chapter` *(or invoke `/synthesize`)*

All generated notes and cropped figures are written inside [`vault/`](./vault/) organized by book and chapter:
```text
vault/
└── <Book Name>/
    └── Chapter 01 - <Chapter Title>/
        ├── 00 - Chapter 01 MOC.md
        ├── 1.1 Dynamic Systems.md
        ├── 1.2 Models.md
        ├── 1.3 An Archetypical Problem - ARX Models and Linear Least Squares.md
        └── assets/
            └── fig_1_3_arx.png
```
*(You can open `vault/` directly as an Obsidian vault, or drag any `<Book Name>` folder into an existing Obsidian vault at any time without breaking a single link or image.)*
