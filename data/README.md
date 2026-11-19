# Structured learning data

Organize machine-readable content into `vocabulary/`, `collocations/`, `questions/`, `transcripts/` and `answer-keys/`. Prefer JSON/JSONL with stable IDs and source provenance. Store explanatory teaching notes as Markdown.

Start from `../templates/collocation.example.json` and `../templates/question.example.json`; those files are **templates, not verified records**.

Never treat AI-generated answer keys as official. Don't publish entire commercial books, exam content or audio without redistribution rights. Use `sources/` to register provenance.

SQLite is optional **derived data** for later query/search use. Do not use a generated database as the sole authoritative store.
