# Source Registry

This directory holds the working source registry for Marin Civic Graph.

## Purpose

The source registry is the canonical inventory of source surfaces the project depends on.

It should stay:

- human-readable
- version-controlled
- easy to diff
- easy to extend

## Files

- [sources.yaml](./sources.yaml) — current seed registry
- [import-manifest.yaml](./import-manifest.yaml) — narrowed v1 graph-materialization scope

## Current Scope

The first registry entries focus on:

- San Rafael case study 01
- Marin County Board of Supervisors
- Marin County campaign finance
- a minimal local-media entry for Marin IJ
- criminal court and sheriff source surfaces
- Marin County and San Rafael planning / permit source surfaces

## Reference

Registry schema and field meanings:

- [Source Registry Format](../docs/source-registry-format.md)
- [Source Adapter And Operations Plan](../docs/source-adapter-and-operations-plan.md)

## Notes

- The seed registry is intentionally incomplete.
- Some sources are broad discovery surfaces.
- Some sources are thread-specific tactical pages for case study 01.
- Paywalled or operator-assisted sources are allowed in the registry as long as the access model is explicit.
- The registry is also becoming the place where municipality-specific source quirks, historical backfill targets, and recurring sync cadence get documented.
