# Marin Civic Graph — Codex Context

See ~/.openclaw/workspace/projects/marin-civic-graph.md for full project state.
See ~/.codex/AGENTS.md for global machine conventions.

## Project-Specific
- Stack: planning repo + Python scripts, no app framework yet. Early stage
- Branch strategy: feature branches
- Purpose: searchable graph of Marin County civic process (institutions, meetings, votes, money, records)
- Data layout: data/raw/ (source captures), data/extracted/, data/normalized/
- Registry: registry/ (source registry seeds)
- Decision hygiene:
  - detailed decisions live in `~/.openclaw/workspace/decisions/`
  - compact project decision index lives in `docs/decision-log.md`
  - update `~/.openclaw/workspace/projects/marin-civic-graph.md` when a durable modeling or source decision changes project state
- Non-goals: partisan scorecards, influence scores, unsupported accusations
- Privilege primary-source evidence: agendas, minutes, contracts, filings, 990s, disclosures
- Current scope: Marin County + San Rafael, first case study (homelessness decision chain)
