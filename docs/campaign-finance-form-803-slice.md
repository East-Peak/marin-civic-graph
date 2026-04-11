# Campaign Finance Form 803 Slice

Verified: April 11, 2026

This note takes the Form 803 / behested-payment thread from a reserve idea into a concrete slice.

The goal is to:

- verify the real local-versus-state filing boundary
- capture the official San Rafael records that currently expose behested-payment guidance
- identify the actual local filing surface
- capture the first true local San Rafael Form 803 sample

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

### San Rafael's public records portal does expose filed local Form 803 records

The missing surface turned out to be the City's public Laserfiche portal, not the SEI NetFile UI.

Using the anonymous public-records search backend, a quoted search for `Form 803` returns a real local filing:

- `Form 803 - Kate Colin`
- entry ID `41053`
- template `FPPC Materials`
- created `9/17/2025 8:21:03 PM`
- modified `9/18/2025 7:52:23 PM`

The same public portal exposes:

- record metadata, including the public-records path
- page text through the document text endpoint

That is enough to treat the portal as a real local filing surface and to promote the first local `Filing` and `MoneyFlow: behested_payment` objects.

### First captured local Form 803 sample

The first promoted local sample is the Kate Colin filing.

The extractable filing text supports these fields cleanly enough to normalize:

- official / filer: `Kate Colin`
- agency: `City of San Rafael`
- payor: `Pacific Gas and Electric Company`
- payee: `Canal Alliance`
- payment date: `2025-08-08`
- amount: `$5,000`
- purpose text: `Affordable Applications Training`

One caution remains: some checkbox-driven subfields in the OCR text are noisy. The data model now promotes the clean fields above while leaving checkbox-only analytics fields conservative.

### Repeatable capture workflow

The current repeatable workflow is:

1. bootstrap an anonymous public Laserfiche session
2. run a small discovery census across:
   - `"Form 803"`
   - `"Form 803 -"`
   - `"Behested Payment Report"`
   - `behested payment`
   - `behested`
3. dedupe actual Form 803 hits by metadata and title
4. capture record metadata
5. capture page text for every discovered page

The repo now includes a dedicated script for this:

- [capture_san_rafael_form803.py](../scripts/capture_san_rafael_form803.py)

As of this verification pass, the broader discovery census still surfaces only one actual filed local Form 803 record, the Kate Colin filing.

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

This slice is now a `guidance + filed sample` slice.

It produces:

- `Record` nodes for San Rafael guidance records
- `Record` nodes for the public-records search result and the first filed local Form 803 sample
- a cleaner source registry for Form 803 work
- a normalized methodology bundle documenting the filing boundary and the first local filing
- the first local `Filing` object for a real San Rafael Form 803
- the first local `MoneyFlow: behested_payment`

## First Captured Records

- San Rafael disclosures page
- San Rafael SEI portal
- San Rafael City Council governance protocols page and PDF
- San Rafael January 20, 2026 City Council agenda-packet page and PDF
- San Rafael public-records Form 803 search results
- Kate Colin Form 803 metadata and page text from the public-records portal

## Promotion Rule

Do not promote a `Form 803` filing or `MoneyFlow: behested_payment` from guidance alone.

Promote those objects only when a filed report or an equivalent official filed-report surface is captured.

For the current Kate Colin sample:

- the filing shell is official and public
- the page text is official and public
- payor, payee, date, amount, and purpose are clean enough to normalize
- checkbox-only subfields should still be treated cautiously until a higher-fidelity page artifact is captured

## Next Move

The next real step in this slice is:

1. turn the public-records portal discovery into a repeatable capture workflow
2. search for additional San Rafael local Form 803 filings beyond the Kate Colin sample
3. decide whether checkbox-derived fields need image verification before broader analytics use
