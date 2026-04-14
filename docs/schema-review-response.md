# Schema Review Response

Verified: April 14, 2026

This is the executed response to [codex-schema-review-prompt.md](./codex-schema-review-prompt.md).

Bottom line:

- the proposed 13-type schema is too collapsed for the actual investigation queries
- it gets some big things right:
  - `Committee` should stay distinct
  - `Seat` earns its keep
  - `AgendaItem` is not noise
  - `Record` has to stay first-class
- but it collapses exactly the wrong temporal and legal boundaries:
  - `SeatService`
  - `Candidacy`
  - `Agreement`
  - `Amendment`
  - `Proceeding`
  - `CaseParticipation`
  - `Place`
  - `Issue`
  - `ValidationCheck`
- it is also missing at least two investigation-relevant concepts:
  - `PublicComment`
  - `BallotMeasure`

My recommendation is not to adopt the 13-type schema as written.

The current repo direction is materially closer to correct.

## Executive Recommendation

Keep these as first-class nodes:

- `Person`
- `Organization`
- `Committee`
- `Seat`
- `SeatService`
- `Election`
- `Candidacy`
- `Meeting`
- `AgendaItem`
- `Decision`
- `Filing`
- `MoneyFlow`
- `Case`
- `Proceeding`
- `CaseParticipation`
- `Project`
- `Agreement`
- `Amendment`
- `Record`
- `Place`
- `Issue`
- `ValidationCheck`

Add when the product needs them:

- `PublicComment`
- `BallotMeasure`

The main design mistake in the 13-type proposal is treating too many legally or temporally distinct things as edge properties. That makes provenance, temporal overlap, and downstream explanation harder than it needs to be.

## 1. Concrete Cypher Queries Against The 13-Type Schema

These queries assume the proposed labels exist:

- `Person`
- `Organization`
- `Committee`
- `Seat`
- `Election`
- `Meeting`
- `AgendaItem`
- `Decision`
- `Filing`
- `MoneyFlow`
- `Case`
- `Project`
- `Record`

They also assume the collapsed concepts are encoded as edge properties, for example:

- `(:Person)-[:HOLDS_SEAT {start_date, end_date}]->(:Seat)`
- `(:Person)-[:RAN_IN {seat_id, outcome}]->(:Election)`
- `(:Organization)-[:AGREEMENT {agreement_type, amount, start_date, project_id}]->(:Project)`
- `(:Person|:Organization)-[:PARTY_TO {role}]->(:Case)`

### Use Case 1: Follow The Money

Question:

- How is a contributor to Kate Colin connected to the 350 Merrydale approvals?

```cypher
MATCH (donor:Person)-[:SOURCE_OF]->(contrib:MoneyFlow)-[:TARGET_OF]->(cmte:Committee)
MATCH (cmte)-[:SUPPORTS]->(cand:Person {name: "Kate Colin"})
MATCH (cand)-[svc:HOLDS_SEAT]->(seat:Seat)
MATCH (cand)-[:CAST_VOTE]->(dec:Decision)-[:ABOUT]->(proj:Project {name: "350 Merrydale Interim Shelter Project"})
MATCH (dec)<-[:RESULTED_IN]-(:AgendaItem)<-[:HAS_ITEM]-(:Meeting)
WHERE contrib.flow_type = "campaign_contribution"
  AND date(contrib.date) <= date(dec.date)
  AND (svc.end_date IS NULL OR date(svc.end_date) >= date(dec.date))
RETURN donor.name, contrib.amount, cmte.name, cand.name, seat.name, dec.title, proj.name
ORDER BY dec.date, contrib.amount DESC;
```

Why this is awkward:

- `SeatService` being an edge means the officeholding boundary is harder to explain and audit.
- There is nowhere to attach evidence or confidence for the service window itself.
- The query assumes a direct `CAST_VOTE` edge from person to decision, but in practice the repo often wants a fuller vote chain with meeting / item / decision provenance.

### Use Case 2: Conflict Of Interest

Question:

- Did Kate Colin vote on a project involving an entity disclosed on a Form 700?

```cypher
MATCH (p:Person {name: "Kate Colin"})-[:FILED]->(f:Filing {form_type: "form_700"})
MATCH (f)-[:DISCLOSES_INTEREST_IN]->(org:Organization)
MATCH (p)-[:CAST_VOTE]->(dec:Decision)-[:ABOUT]->(proj:Project)
MATCH (org)-[:RELATED_TO]->(proj)
RETURN p.name, f.filing_date, org.name, dec.title, proj.name, dec.date
ORDER BY dec.date DESC;
```

Why this is awkward:

- The schema has no dedicated place to represent disclosed-interest entries.
- A Form 700 filing is not itself the disclosed interest. It is the container.
- If `DISCLOSES_INTEREST_IN` hangs directly off the filing, you lose the row-level or statement-level object needed for evidence and later reconciliation.

### Use Case 3: Temporal Coincidence

Question:

- Show contributions and government actions involving the same parties within 30 days.

```cypher
MATCH (donor:Person)-[:SOURCE_OF]->(mf1:MoneyFlow)-[:TARGET_OF]->(cmte:Committee)
MATCH (cand:Person)<-[:SUPPORTS]-(cmte)
MATCH (cand)-[:CAST_VOTE]->(dec:Decision)-[:ABOUT]->(proj:Project)
MATCH (counterparty:Organization)-[:AGREEMENT]->(proj)
WHERE abs(duration.inDays(date(mf1.date), date(dec.date)).days) <= 30
RETURN donor.name, mf1.amount, mf1.date, cand.name, dec.title, dec.date, proj.name, counterparty.name
ORDER BY mf1.date, dec.date;
```

Why this is awkward:

- `Agreement` as an edge is lossy here. You can test existence, but you cannot cleanly rank, cite, amend, or explain it.
- If multiple agreements exist around the same project, edge properties become a tangle of relationship filtering rather than an inspectable object.

### Use Case 4: Pattern Detection

Question:

- Which actors recur across unrelated decisions, filings, and money flows?

```cypher
MATCH (a)
WHERE a:Person OR a:Organization OR a:Committee
OPTIONAL MATCH (a)-[:SOURCE_OF|TARGET_OF]-(mf:MoneyFlow)
OPTIONAL MATCH (a)-[:FILED|CONTROLLED_BY|SUPPORTS|TREASURER_OF]-(f:Filing)
OPTIONAL MATCH (a)-[:CAST_VOTE|PARTY_TO|RELATED_TO]-(d:Decision)
WITH a,
     count(DISTINCT mf) AS money_count,
     count(DISTINCT f) AS filing_count,
     count(DISTINCT d) AS decision_count
WHERE money_count + filing_count + decision_count > 3
RETURN labels(a), coalesce(a.name, a.title) AS actor, money_count, filing_count, decision_count
ORDER BY money_count + filing_count + decision_count DESC;
```

Why this is awkward:

- Without `Issue` and `Place` nodes, “unrelated” becomes much harder to define.
- Without `ValidationCheck`, noisy OCR actors and low-quality extractions are harder to quarantine from pattern queries.
- Without `Program` or `Agreement` nodes, some recurrence collapses into generic `Organization RELATED_TO Project`, which is weaker than the real civic relationship.

### Use Case 5: Decision Archaeology

Question:

- What was discussed when Resolution 15336 was adopted, and what records backed it?

```cypher
MATCH (dec:Decision {title: "Resolution 15336 appropriating $2,256,400 and authorizing $2,002,400 in contracts"})
MATCH (item:AgendaItem)-[:RESULTED_IN]->(dec)
MATCH (meeting:Meeting)-[:HAS_ITEM]->(item)
OPTIONAL MATCH (dec)-[:BACKED_BY]->(rec:Record)
OPTIONAL MATCH (item)-[:BACKED_BY]->(itemRec:Record)
RETURN meeting.date, meeting.name, item.title, item.number,
       collect(DISTINCT rec.title) AS decision_records,
       collect(DISTINCT itemRec.title) AS item_records;
```

Why this is awkward:

- This query is fine only because `AgendaItem` stays a node.
- If public comments or speaker appearances matter, the 13-type schema has no good home for them.
- “Who spoke during public comment?” is a real investigation question and is not solved by `Meeting`, `AgendaItem`, `Decision`, and `Record` alone.

### Use Case 6: Legal Pressure Mapping

Question:

- Which court cases constrained San Rafael sanctioned-camping decisions?

```cypher
MATCH (c:Case)-[:CONSTRAINS]->(dec:Decision)-[:ABOUT]->(proj:Project)
WHERE proj.name IN [
  "San Rafael sanctioned camping program",
  "350 Merrydale Interim Shelter Project"
]
OPTIONAL MATCH (party)-[r:PARTY_TO]->(c)
RETURN c.name, c.docket_number, dec.title, proj.name,
       collect(DISTINCT {party: coalesce(party.name, party.title), role: r.role}) AS parties
ORDER BY c.filed_date, dec.date;
```

Why this is awkward:

- `Proceeding` being collapsed means injunctions, dismissals, and motion hearings become hard to query as first-class temporal events.
- `CaseParticipation` as an edge is survivable for simple party lists, but materially weaker once you need party-specific evidence, counsel changes, or role changes over time.

## 2. Collapsed Types That Should Be Restored

This is where the 13-type proposal fails hardest.

### Restore `SeatService`

Why:

- officeholding is not just a property of `Person -> Seat`
- it is a bounded service window with evidence, election linkage, and temporal semantics

Concrete query that is materially harder without it:

```cypher
MATCH (p:Person {name: "Kate Colin"})-[svc:HOLDS_SEAT]->(seat:Seat)
MATCH (dec:Decision)-[:ABOUT]->(:Project {name: "350 Merrydale Interim Shelter Project"})
WHERE date(dec.date) >= date(svc.start_date)
  AND (svc.end_date IS NULL OR date(dec.date) <= date(svc.end_date))
RETURN p.name, seat.name, dec.title, dec.date;
```

Why this should be a node instead:

- you want to attach evidence records to the service window
- you want to distinguish current vs historical service explicitly
- you want service windows to participate in dossiers and time-based summaries

This is exactly why the current repo keeps `SeatService`.

### Restore `Candidacy`

Why:

- candidacy is not just “person ran in election”
- it binds person, seat, election, committee, result, and evidence into one contest-specific object

Concrete query that is cleaner with a node:

```cypher
MATCH (cand:Candidacy)-[:FOR_PERSON]->(p:Person {name: "Rachel Kertz"})
MATCH (cand)-[:IN_ELECTION]->(e:Election)
MATCH (cand)-[:FOR_SEAT]->(s:Seat)
OPTIONAL MATCH (cand)-[:HAS_COMMITTEE]->(c:Committee)
RETURN p.name, e.name, s.name, cand.outcome, collect(c.name);
```

With an edge-only model, committee linkage and outcome provenance get spread across unrelated relationships.

### Restore `Agreement`

Why:

- contracts, grant agreements, collaboration agreements, brokerage agreements, PSAs, and design agreements are not just flavored edges
- they have their own records, dates, amounts, amendments, and evidentiary life

Concrete query that is materially harder without it:

```cypher
MATCH (proj:Project {name: "350 Merrydale Interim Shelter Project"})<-[:ABOUT]-(dec:Decision)
MATCH (agr:Agreement)-[:FOR_PROJECT]->(proj)
OPTIONAL MATCH (amd:Amendment)-[:AMENDS]->(agr)
RETURN dec.title, agr.name, agr.authorized_amount, count(amd) AS amendment_count;
```

This is exactly the Merrydale and Downtown Library problem the current repo already ran into.

### Restore `Amendment`

Why:

- amendments are common in local government
- they are not just changed amounts
- they are separate actions with separate records and often separate decisions

Concrete query:

```cypher
MATCH (agr:Agreement)-[:FOR_PROJECT]->(:Project {name: "Downtown Library Renovation Project"})
MATCH (amd:Amendment)-[:AMENDS]->(agr)
RETURN agr.name, amd.name, amd.authorized_amount, amd.effective_date
ORDER BY amd.effective_date;
```

If amendments live only as edge properties, this query is a mess.

### Restore `Proceeding`

Why:

- injunctions, motion hearings, dismissals, appellate opinions, and judgments are distinct legal events
- they matter temporally and investigatively

Concrete query:

```cypher
MATCH (c:Case {name: "Boyd v. City of San Rafael"})-[:HAS_PROCEEDING]->(p:Proceeding)
RETURN p.proceeding_type, p.occurred_at, p.status
ORDER BY p.occurred_at;
```

The current repo already proves this is valuable.

### Restore `CaseParticipation`

Why:

- legal parties are not always static
- roles, evidence, and time bounds matter

Concrete query:

```cypher
MATCH (cp:CaseParticipation)-[:IN_CASE]->(c:Case {name: "Boyd v. City of San Rafael"})
OPTIONAL MATCH (cp)-[:FOR_PERSON|FOR_ORGANIZATION]->(party)
RETURN party.name, cp.role, cp.start_date;
```

As an edge-only construct, it is adequate for toy queries and bad for audited legal context.

### Restore `Place`

Why:

- place is not just metadata
- it is often the join surface across cases, projects, programs, and jurisdictions

Concrete query:

```cypher
MATCH (pl:Place {name: "San Rafael"})<-[:IN_JURISDICTION]-(proj:Project)
OPTIONAL MATCH (case:Case)-[:CONCERNS_PLACE]->(pl)
RETURN pl.name, collect(DISTINCT proj.name), collect(DISTINCT case.name);
```

This is why the current repo uses `Place`.

### Restore `Issue`

Why:

- “homelessness,” “encampments,” and “camping ordinance” are not just tags once you need cross-thread comparison

Concrete query:

```cypher
MATCH (i:Issue {name: "camping ordinance"})<-[:HAS_ISSUE]-(x)
RETURN labels(x), count(*) AS linked_objects;
```

This is much cleaner and more composable than string tags everywhere.

### Restore `ValidationCheck`

Why:

- validation is not just pipeline metadata if the product wants to answer “what still does not reconcile cleanly?”
- this is already one of the repo’s active question types

Concrete query:

```cypher
MATCH (v:ValidationCheck)-[:CHECKS]->(f:Filing)
WHERE v.status <> "reconciled"
RETURN f.title, v.check_type, v.delta_amount, v.status
ORDER BY abs(v.delta_amount) DESC;
```

The current repo already proved this is a product-facing graph object, not just internal QA.

## 3. Should Any Of The 13 Be Collapsed Further?

Very little.

### `Committee` should stay distinct

Do not merge it into `Organization`.

Why:

- FPPC committee structure is legally distinct
- follow-the-money queries become weaker if campaign entities get flattened into the general org pool

### `Seat` should stay distinct

Do not collapse it.

Why:

- district seats and mayoral seats are durable civic structures
- campaigns, officeholding, and voting all anchor to them

### `AgendaItem` should stay distinct

Do not collapse it.

Why:

- not every item becomes a decision
- many investigation questions are item-level, not decision-level

### `Record` should stay distinct

Do not collapse it into `Filing`.

Why:

- filings are one kind of record
- staff reports, minutes, court orders, agenda packets, and press releases are also core evidence

### The only plausible further collapse: `Person` + `Organization` -> `Actor`

This is the only serious candidate.

It would help polymorphic queries like:

```cypher
MATCH (a:Actor)-[:SOURCE_OF|TARGET_OF]-(mf:MoneyFlow)
RETURN a.name, count(mf);
```

But I would still not recommend it for this project.

Why:

- legal identity matters
- person-specific and org-specific constraints are real
- `Person` and `Organization` are still worth keeping separate

So: practically no further collapse is attractive here.

## 4. Missing Types

Two missing types matter immediately.

### Missing type: `PublicComment`

This is the biggest omission relative to the stated use cases.

Use case 5 explicitly asks:

- who spoke during public comment?

That is not solved by `Meeting`, `AgendaItem`, `Decision`, `Record`.

You need something like:

- `PublicComment`
- `SpeakerAppearance`
- or `Testimony`

Concrete query:

```cypher
MATCH (m:Meeting {date: date("2024-08-19")})-[:HAS_ITEM]->(ai:AgendaItem)
MATCH (pc:PublicComment)-[:ON_ITEM]->(ai)
MATCH (pc)-[:BY]->(p:Person)
RETURN ai.title, p.name, pc.position, pc.summary
ORDER BY ai.number, p.name;
```

Without a node like this, “who spoke?” remains a document-mining problem, not graph truth.

### Missing type: `BallotMeasure`

Why:

- measure committees, candidate committees, and independent expenditures are not the same thing
- elections involving measures want a durable object that is not just a generic project

Concrete query:

```cypher
MATCH (bm:BallotMeasure)<-[:ABOUT]-(e:Election)
MATCH (cmte:Committee)-[:SUPPORTS|OPPOSES]->(bm)
MATCH (cmte)<-[:TARGET_OF]-(:MoneyFlow)
RETURN bm.name, e.name, cmte.name;
```

### Honorable mention: `DisclosureInterest`

If the product seriously wants conflict-of-interest work, eventually it needs a structured thing between `Filing` and `Organization`.

That can be:

- a node
- or a heavily structured relationship

But the current 13-type proposal does not solve it cleanly.

## 5. Testing The `Organization` Subtype Approach

Three queries that depend on organization subtypes:

### Query A: government body vs nonprofit counterparty around a decision

```cypher
MATCH (dec:Decision)-[:ABOUT]->(:Project {name: "350 Merrydale Interim Shelter Project"})
MATCH (org:Organization)-[:RELATED_TO]->(dec)
WHERE org.subtype IN ["government", "nonprofit"]
RETURN org.name, org.subtype;
```

### Query B: campaign vendor recurrence vs civic vendor recurrence

```cypher
MATCH (org:Organization)-[:SOURCE_OF|TARGET_OF]-(mf:MoneyFlow)
WHERE org.subtype IN ["business", "political"]
RETURN org.name, org.subtype, count(mf) AS flow_count
ORDER BY flow_count DESC;
```

### Query C: court entities influencing local decisions

```cypher
MATCH (org:Organization {subtype: "court"})<-[:HEARD_IN]-(c:Case)-[:CONSTRAINS]->(d:Decision)
RETURN org.name, c.name, d.title;
```

Evaluation:

- subtype properties are acceptable for small domains
- they get messy fast when government bodies, departments, courts, commissions, and nonprofits all live under one label
- they are workable for storage
- they are weaker for readability, index strategy, and query clarity

My recommendation:

- either restore `Institution`
- or use secondary labels in projection, for example:
  - `:Organization:GovernmentBody`
  - `:Organization:Nonprofit`
  - `:Organization:Business`
  - `:Organization:Court`

Pure subtype-property-only modeling is too flat for a civic graph with this many organization roles.

## 6. Evaluating The Edge-With-Properties Approach

This is where the 13-type design looks clean on paper and worse in practice.

### Join query: Which officeholders had active seat service when agreements tied to 350 Merrydale were authorized?

In the collapsed model:

```cypher
MATCH (p:Person)-[svc:HOLDS_SEAT]->(s:Seat)
MATCH (o:Organization)-[agr:AGREEMENT]->(proj:Project {name: "350 Merrydale Interim Shelter Project"})
MATCH (dec:Decision)-[:ABOUT]->(proj)
WHERE date(dec.date) >= date(svc.start_date)
  AND (svc.end_date IS NULL OR date(dec.date) <= date(svc.end_date))
  AND date(agr.start_date) <= date(dec.date)
RETURN p.name, s.name, agr.agreement_type, agr.amount, dec.title;
```

Why this is weak:

- the seat-service relationship has no durable ID
- the agreement relationship has no durable ID
- amendments become relationship mutation or chained relationship tricks
- evidence attachment is awkward on relationships
- you cannot point a dossier or read model cleanly at a relationship as a civic object

This is exactly why the current repo restored:

- `SeatService`
- `Agreement`
- `Amendment`

### Join query: Which candidacies overlap with committees and later officeholding?

Collapsed:

```cypher
MATCH (p:Person)-[ran:RAN_IN]->(e:Election)
MATCH (cmte:Committee)-[:SUPPORTS]->(p)
MATCH (p)-[svc:HOLDS_SEAT]->(s:Seat)
WHERE ran.seat_id = s.id
RETURN p.name, e.name, ran.outcome, s.name, svc.start_date;
```

Again:

- edge properties work for a toy graph
- they get brittle once multiple committees, elections, and seat windows exist

Intermediate nodes are cleaner because they can carry:

- IDs
- evidence
- notes
- status
- confidence
- separate read models

## Recommendation

Do not adopt the 13-type schema as proposed.

Specific calls:

### Keep

- `Committee`
- `Seat`
- `AgendaItem`
- `Decision`
- `Filing`
- `MoneyFlow`
- `Case`
- `Project`
- `Record`
- `Meeting`
- `Person`
- `Organization`
- `Election`

### Restore

- `SeatService`
- `Candidacy`
- `Agreement`
- `Amendment`
- `Proceeding`
- `CaseParticipation`
- `Place`
- `Issue`
- `ValidationCheck`

### Add

- `PublicComment`
- `BallotMeasure`

### Conditional / later

- `DisclosureInterest`

If you want the blunt version:

- the 13-type proposal is elegant in the wrong way
- it optimizes label count instead of investigation quality
- it pushes too much temporal and legal structure into edge properties
- and it would make the graph harder to explain, harder to audit, and harder to extend once real civic data accumulates

The current repo’s direction is better:

- keep more first-class temporal and legal objects
- keep provenance inspectable
- let read models collapse things for consumption later
- do not collapse graph truth just to make the label list feel cleaner
