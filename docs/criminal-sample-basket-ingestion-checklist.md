# Criminal Sample Basket Ingestion Checklist

Date drafted: April 10, 2026

This checklist turns the criminal sample basket into an execution plan.

References:

- [Criminal Justice Submodel](./criminal-justice-submodel.md)
- [Criminal Sample Basket Source Bundle](./criminal-sample-basket-source-bundle.md)

## Goal

Produce one small public-record criminal bundle that pressure-tests:

- `Case`
- `Proceeding`
- `Charge`
- `CustodyEvent`
- `ReleaseDecision`
- `AttorneyRepresentation`
- `Disposition`
- `Sentence`
- `Record` with `legal_record`
- the joins back to `Actor`, `Institution`, and `Place`

## Basket

The first pass covers:

1. one booking-first open case
2. one filed-and-disposed case
3. one warrant-linked or comparable control thread

## Phase 0: Source Registration

### Must Register First

- [ ] Marin Superior Court `ePortal`
- [ ] Marin Superior Court `Court Records & Exhibits`
- [ ] Marin Superior Court `Judicial Assignments`
- [ ] Marin Superior Court `Judicial Biographies`
- [ ] Marin Sheriff `Detention Bureau`
- [ ] Marin Sheriff `Warrants`
- [ ] Marin Sheriff `Records`
- [ ] Marin County DA newsroom

### Registry Metadata To Capture

- [ ] source ID
- [ ] source owner
- [ ] source category
- [ ] fetch strategy
- [ ] expected objects
- [ ] review risk
- [ ] notes on public-access limits

## Phase 1: Raw Surface Capture

### Court Surfaces

- [x] capture the `ePortal` overview page as raw HTML
- [ ] capture `Court Records & Exhibits` as raw HTML
- [x] capture `Judicial Assignments` as raw HTML
- [x] capture `Judicial Biographies` as raw HTML
- [x] note that the public `ePortal` landing page appears to require registration before live case search can be used
- [x] note that pre-June 20, 2023 criminal matters remain in `EJUS`, not `ePortal`

### Sheriff Surfaces

- [x] capture the `Detention Bureau` page as raw HTML
- [x] identify the booking-log access path from the detention or FAQ surface
- [x] capture the `Warrants` page as raw HTML
- [x] capture the `Records` page as raw HTML
- [x] identify the warrant-search access path from the sheriff warrants page
- [x] note that the public booking-log page says it covers the last 48 hours for people still in custody plus a complete inmate list at runtime
- [x] note that the public booking-log page offers an optional last-name filter and approximate bail warning

### Optional Discovery Surface

- [ ] capture the DA newsroom landing page as raw HTML
- [ ] mark any criminal case statements as discovery-only unless they can be linked back to court records

## Phase 2: Sample Selection

Important boundary:

- [ ] do not put private defendant names into committed planning docs during sample selection
- [ ] keep the first live sample selection operator-only unless and until we define a safe private storage boundary

### Slot A: Booking-First Open Case

- [ ] select one adult current or recent in-custody thread with visible booking and next-hearing information
- [ ] record why the sample was chosen
- [ ] record which surfaces expose the join path

### Slot B: Filed And Disposed Case

- [ ] select one adult case with visible hearings and disposition
- [ ] prefer a case where at least one sentencing or judgment surface is discoverable
- [ ] record any places where only titles, not documents, are public

### Slot C: Warrant-Linked Or Control Thread

- [ ] select one adult warrant-linked or similar control thread
- [ ] confirm whether the warrant surface can be joined back to case and proceeding data

## Phase 3: Record Extraction

### Booking / Sheriff Side

- [ ] create `Record` candidates for booking-log or detention outputs
- [ ] extract booking number if visible
- [ ] extract booking-stage charges
- [ ] extract bail, release, and next-hearing fields where public

### Court Side

- [ ] create `Record` candidates for case-index or calendar surfaces
- [ ] extract case number
- [ ] extract hearing dates and proceeding labels
- [ ] extract filed-document titles if visible
- [ ] extract judge or department assignment

### Judge Context

- [ ] create judge `Actor` candidates from judicial assignments
- [ ] enrich them with appointment / election context from biographies where useful

### Outcome Side

- [ ] extract disposition labels
- [ ] extract sentence or supervision outcome if public
- [ ] preserve uncertainty where outcome is only partially visible

## Phase 4: Object Modeling

### Slot A

- [ ] create `Actor` for the defendant if strong enough identifiers exist
- [ ] create `CustodyEvent`
- [ ] create booking-stage `Charge`
- [ ] create `Case`
- [ ] create the next `Proceeding`
- [ ] create `ReleaseDecision` only if the surface explicitly supports it

### Slot B

- [ ] create `Case`
- [ ] create filed `Charge` objects
- [ ] create one or more `Proceeding`
- [ ] create `AttorneyRepresentation` where public
- [ ] create `Disposition`
- [ ] create `Sentence` if supported

### Slot C

- [ ] create `Record` for the warrant surface
- [ ] create or join the related `Case`
- [ ] create linked `Proceeding` if public
- [ ] keep unresolved joins in `Claim`, not canonical objects

## Phase 5: Join Validation

### Must Prove

- [ ] booking-stage charge to case join
- [ ] case to proceeding join
- [ ] proceeding to judge join
- [ ] filed charge to disposition join
- [ ] disposition to sentence join where available

### Must Not Overclaim

- [ ] booked charge is the same as filed charge without evidence
- [ ] assigned department is the same as presiding judge on every later proceeding
- [ ] public-access case titles imply full document access
- [ ] DA statement alone is enough to create a canonical disposition

## Phase 6: Minimum Deliverable

The first usable criminal deliverable should be:

- [ ] one sample bundle doc describing the three selected slots
- [ ] raw captures for the official source surfaces used
- [ ] one normalized sample per slot
- [ ] one list of joins that held cleanly
- [ ] one list of joins that stayed ambiguous
- [ ] one recommendation for whether criminal justice should expand next or pause behind permits / applications / denials

## Blocking Questions

- [x] how discoverable is the live booking-log surface for reproducible capture?
- [ ] how should the project handle person-level booking and warrant surfaces without committing private names into the repo?
- [ ] can public `ePortal` access expose enough to distinguish booked charges, filed charges, and dispositions once a public account is registered?
- [ ] how often are attorney roles visible without restricted access?
- [ ] how often are sentence outcomes visible without minute orders or records requests?
- [ ] do we need a dedicated records-request workflow before criminal ingestion can move beyond planning?

## Practical Order Of Operations

If doing this manually first, the order should be:

1. capture the court and sheriff source surfaces
2. select one sample for each slot
3. model the booking-first slot
4. model the filed-and-disposed slot
5. model the warrant-linked or control slot
6. review which joins survived and which did not

## Status As Of April 10, 2026

- the criminal submodel now exists in the schema docs
- the official source surfaces are identified and the first court and sheriff landing surfaces are captured as raw HTML
- the remaining work is selecting the first three sample slots in an operator-only workflow and proving the joins against real public records
