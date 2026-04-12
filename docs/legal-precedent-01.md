# Legal Precedent 01

`legal-precedent-01` is the first normalized legal bundle.

It starts narrowly with `Boyd v. City of San Rafael` and is meant to prove the legal / constraint lane against one real local case before widening into `Grants Pass`, `Coalition on Homelessness`, or the Marin Civil Grand Jury basket.

## What It Contains

- one court-origin `dismissal_order` record:
  - August 7, 2024 `Order Granting Defendant's Motion to Dismiss`
- linked city-side legal context records:
  - Boyd dismissal release
  - June 28, 2024 `Grants Pass` statement
  - September 2, 2024 `Grants Pass` explainer
  - sanctioned camping program page
- first normalized legal objects:
  - `Case`
  - `Proceeding`
  - `CaseParticipation`
  - crosswalk back to the August 19, 2024 item `5.a` decision chain

## Why It Is Narrow

This bundle is intentionally not the whole judicial pressure-test basket.

The repo now has a real local legal bundle, but the stronger architectural move is:

1. prove the case/proceeding/program/decision joins on `Boyd`
2. preserve the missing TRO / preliminary-injunction court-order gap explicitly
3. widen only after the first local legal slice is clean

## Current Boundary

The bundle is normalized and durable, but it is not yet part of the narrowed `graph-v1` import manifest.

That is deliberate. The legal lane now has a real bundle, but it still needs:

- direct TRO and preliminary-injunction order capture
- one follow-on import decision for `Case`, `Proceeding`, and `CaseParticipation`
- later comparison against `Grants Pass` and other external constraint sources

## Primary Artifacts

- [Boyd legal bundle](../data/normalized/legal-precedent-01/bundle-01.json)
- [Boyd dismissal-order extract](../data/extracted/san-rafael-boyd-dismissal-order/2026-04-12.json)
- [Boyd dismissal-order text](../data/extracted/san-rafael-boyd-dismissal-order/order.txt)
