# Campaign Finance Form 803 Slice

Verified: April 11, 2026

This note takes the Form 803 / behested-payment thread from a reserve idea into a concrete slice.

The goal is not to pretend we already have a clean local Form 803 filing feed.

The goal is to:

- verify the real local-versus-state filing boundary
- capture the official San Rafael records that currently expose behested-payment guidance
- identify the exact local filing-surface gap that still blocks the first true local Form 803 sample

## What The Official Surfaces Show

### Local officials do not file Form 803 with the FPPC

The governing rule is explicit in the official FPPC Form 803 instructions:

- local officials file Form 803 with their local agency
- the local agency then forwards a copy to the filing officer who receives the official's original campaign statements
- local officials do not file Form 803 with the FPPC

This matters because it means the FPPC state search surface is not the right primary source for San Rafael city officials.

### FPPC public Form 803 search is state-level, not local

The current FPPC Form 803 search page says the searchable data covers:

- members of the Senate
- members of the Assembly
- statewide elected officers

That page is still important, but only as:

- official behavioral guidance for what Form 803 means
- a model for how the graph should normalize payor, payee, amount, and purpose
- a warning not to mistake the FPPC search page for a complete local-government behested-payment index

### San Rafael's public disclosure and SEI surfaces are not yet a clean Form 803 source

As of this verification pass:

- the San Rafael disclosures page is clearly a public disclosure spine, but the visible page content foregrounds Form 700, Form 804, and Form 806
- the San Rafael SEI NetFile portal is a Form 700 search surface, not a visible Form 803 portal
- the visible statement-type options on the public SEI portal are:
  - `Annual`
  - `Assuming`
  - `Leaving`
  - `Candidate`
  - `Ethics Training`
  - `Other Training`

No `Form 803` or `Behested` option is visible in the public SEI portal UI that is currently captured.

### San Rafael does publish behested-payment guidance inside City Council governance records

The strongest local public records found in this slice are:

- the February 5, 2026 City Council governance / roles / communication protocols record
- the January 20, 2026 City Council agenda packet carrying the same Attachment A guidance

Both records include the same behested-payment guidance attachment that states:

- Form 803 is due within 30 days
- local elected officials file with the agency filing officer, typically the City Clerk
- Form 803 must be posted on the agency website within 30 days of filing

That guidance is not itself a filed Form 803 report.

But it is strong evidence for:

- the filing rule
- the expected posting obligation
- the correct local join target: City Clerk / local agency, not FPPC search

## What This Slice Produces

This slice is currently a `guidance-and-surface` slice, not a `filed-payment` slice.

It produces:

- `Record` nodes for San Rafael guidance records
- a cleaner source registry for Form 803 work
- a normalized methodology bundle documenting the filing boundary
- one explicit open question for the missing local filed-report surface

It does not yet produce:

- a local `Filing` object for a real San Rafael Form 803
- a `MoneyFlow` object for an actual behested payment
- payor/payee/amount normalization from a filed local report

## First Captured Records

- San Rafael disclosures page
- San Rafael SEI portal
- San Rafael City Council governance protocols page and PDF
- San Rafael January 20, 2026 City Council agenda-packet page and PDF

## Promotion Rule

Do not promote a `Form 803` filing or `MoneyFlow: behested_payment` from guidance alone.

Only promote those objects when a filed report or an equivalent official filed-report surface is captured.

## Next Move

The next real step in this slice is:

1. identify the actual local San Rafael surface where filed Form 803 reports are posted
2. capture the first filed local Form 803
3. normalize:
   - filer / officeholder
   - filing officer / agency
   - payor
   - payee
   - amount
   - date
   - charitable / governmental / legislative purpose
