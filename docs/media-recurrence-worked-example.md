# Media Recurrence Worked Example

Verified: April 11, 2026

This note extends the first Marin IJ mention/claim pass into recurrence across two articles and official records.

The point is narrower than a general media pipeline:

- show what a second article should add
- show what recurrence strengthens
- show what still should not be promoted

## Selected Second Record

- article: `San Rafael prepares site for authorized homeless camp`
- Marin Independent Journal
- published: `2024-09-20T20:48:05Z`
- canonical record ID: `record-mij-2024-09-20-prepares-site-authorized-camp`

## Why This Article

This one was better than the October 5 or November 10 articles because it overlaps with the existing evidence spine in four useful ways:

- `Mel Burnette` recurs against official city records
- `Mark Shotwell` recurs against official submitted correspondence
- `Mark Rivera` recurs against the earlier article and the official minutes speaker list
- `Defense Block Security` and `Downtown Streets Team` recur against the official contract/program layer

That makes it a better recurrence test than an article that only repeats generic council language.

## Capture Path

- raw capture: [manifest.json](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-ij-2024-09-20-authorized-camp-preparation-article/2026-04-11/manifest.json)
- raw response: [response.json](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-ij-2024-09-20-authorized-camp-preparation-article/2026-04-11/response.json)
- extracted layer: [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/marin-ij-2024-09-20-authorized-camp-preparation-article/2026-04-11.json)
- recurrence layer: [marin-ij-recurrence-example-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-recurrence-example-01.json)

Like the first article, this one was captured through the public WordPress post API.

## Recurrence Outcomes

### 1. Strong cross-source recurrence: Mark Shotwell

The repo already had:

- official submitted correspondence from `Mark Shotwell`
- official affiliation to `Ritter Center`

The second article prints:

- `Mark Shotwell, chief executive officer of the Ritter Center`

Result:

- accept this as a high-confidence recurring canonical actor pattern

This is the cleanest example so far because the media wording and the official wording are effectively aligned.

### 2. Strong official-to-media recurrence: Mel Burnette

The repo already had:

- official city records naming `Mel Burnette` as the homelessness / housing analyst

The second article prints:

- `Mel Burnette, the city's housing and homelessness analyst`

Result:

- accept a high-confidence case-level recurrence pattern for the same actor

### 3. Repeated but still unresolved: Mark Rivera

The repo now has:

- one August 24 Marin IJ mention: `Mark Rivera, an unhoused resident of San Rafael`
- one official minutes speaker-list occurrence: `Mark Rivera`
- one September 20 Marin IJ mention: `Mark Rivera, who filed the suit`

Result:

- treat this as one unresolved case-scoped person cluster
- do not promote it into the canonical seed layer yet

This is the important negative example. Repetition improves confidence that the occurrences belong together, but it still does not force canonical promotion.

### 4. Stable organization recurrence: Defense Block Security and Downtown Streets Team

These labels now recur across:

- official August 19 records
- the August 24 article
- the September 20 article

Result:

- accept these as stable organization recurrence patterns within the case

This is often easier than person-level recurrence because organization labels are less noisy.

## What This Changes

The media layer now has two proven steps:

1. one article can become `Mention -> Claim -> Actor`
2. a second article can become a recurrence pass over those same actors and organizations

That is enough to stop treating Marin IJ as a purely citation-only source in this thread.

## What Still Stays Out

- no blanket activist labeling
- no NGO-affiliation inference from proximity or tone
- no canonical promotion for a repeated named person without stronger identity evidence

## Next Move

The next useful media step is no longer “can we parse one article?”

It is:

- whether the same named people recur across three or more articles
- whether recurring local speakers also recur in campaign, disclosure, or organization records
- whether article framing omits affiliations that are explicit in stronger public records
