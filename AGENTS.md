# Marin Civic Graph — Codex Context

See ~/.openclaw/workspace/projects/marin-civic-graph.md for full project state.
See ~/.codex/AGENTS.md for global machine conventions.

## Project-Specific
- Stack: planning repo + Python scripts, no app framework yet. Early stage
- Branch strategy: feature branches
- Purpose: searchable graph of Marin County civic process (institutions, meetings, votes, money, records)
- Data layout: data/raw/ (source captures), data/extracted/, data/normalized/
- Registry: registry/ (source registry seeds)
- Current graph state:
  - graph-v1 projection exists and is active
  - fixed query pack is passing
  - projected JSON read models exist under `data/projected/graph-v1/views/`
  - local viewer is a thin consumer only, not source truth
- First recovery docs for collaborators:
  - `README.md`
  - `docs/claude-collaboration-handoff.md`
  - `docs/question-set-v1.md`
  - `docs/open-questions.md`
  - `docs/decision-log.md`
- Decision hygiene:
  - detailed decisions live in `~/.openclaw/workspace/decisions/`
  - compact project decision index lives in `docs/decision-log.md`
  - update `~/.openclaw/workspace/projects/marin-civic-graph.md` when a durable modeling or source decision changes project state
- Non-goals: partisan scorecards, influence scores, unsupported accusations
- Privilege primary-source evidence: agendas, minutes, contracts, filings, 990s, disclosures
- Current scope: Marin County + San Rafael, first case study (homelessness decision chain)
- Current discipline:
  - do not add ontology by default
  - do not widen source coverage unless it materially improves the bounded question set
  - do not promote noisy one-off campaign row actors into canonical actors
