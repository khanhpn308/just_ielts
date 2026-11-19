# just_ielts — Personal IELTS Knowledge & Learning System

A Markdown-first repository for learning IELTS Academic Reading, Listening, Writing and Speaking, with atomic principles, structured exercise data, error logs and progress reviews.

## Start here

1. **Learning principles:** [principles/README.md](principles/README.md) and [principles/INDEX.md](principles/INDEX.md).
2. **Original eight golden principles:** [principles/general/8_golden_principles](principles/general/8_golden_principles) — preserved as originally written.
3. **Agent behavior:** [AGENTS.md](AGENTS.md).
4. **Study data:** [data/README.md](data/README.md); copy JSON patterns from `templates/`.
5. **Progress and errors:** [progress/README.md](progress/README.md); copy logs from `progress/templates/`.

## Architecture

```text
just_ielts/
├── AGENTS.md                  # Retrieval and tutoring rules
├── principles/                # Atomic .md files with YAML frontmatter
│   ├── INDEX.md               # Generated compact lookup table
│   ├── general/                # General learning methodology
│   ├── reading/                # Core + question types
│   ├── listening/              # Core + parts
│   ├── writing/                # Core + Task 1/Task 2
│   └── speaking/               # Core + Part 1/2/3
├── data/                      # Vocabulary, exercises, transcripts, keys
├── progress/                  # Sessions, error logs, weekly reviews
├── templates/                 # Reusable Markdown and JSON templates
├── sources/                   # Provenance records, not unlicensed PDFs
├── scripts/                   # Metadata/index and JSON validators
└── .github/workflows/         # Repository validation
```

## Add a new principle

1. Copy `templates/principle.md` into the matching `principles/<skill>/...` path.
2. Give it a **globally unique ID**, select `skill`, `question_types`, and concrete `triggers`.
3. Write **when to use**, **procedure**, **limits**, and **source references**. Never claim a source is verified without checking it.
4. Run the index builder:

```bash
python -m pip install -r requirements-dev.txt
python scripts/build_principles_index.py
python scripts/build_principles_index.py --check
python scripts/validate_data.py
```

5. Commit the principle *and* refreshed `principles/INDEX.md`. GitHub Actions verifies both.

## Retrieval design

**Identify skill and error → read the small INDEX → open 1–3 matching principle files → verify the original passage/audio/question/answer key → explain → record error after confirmation.**

The index is for discovery. It does not prove that an answer is correct. If no suitable principle exists, say so rather than inventing one.

## Data and privacy

**This repository is public.** Do not publish personal study notes, recordings, contact details, passwords or private/licensed books without deciding that disclosure is acceptable. The ignored `private/` directory is for local-only material; ignored local SQLite databases can be generated from structured data later.

Only publish exam content, books, answer keys and audio when you have permission to redistribute them. Keep source references and verification status separate from AI-created explanations.
