# Actor Resolution Worked Example

Date drafted: April 11, 2026

This note shows how the first identity seed layer should behave on real project records.

The point is not to cover every actor. The point is to show the exact threshold for promotion.

## Example 1: Kate Colin

### Raw observations

- `Kate Colin, Mayor`
- `Mayor Kate Colin`
- `Kate Colin`
- `Kate Colin (she/her/hers)`

### Evidence

- official August 19, 2024 item `5.a` report and packet roster/signature block
- official August 8, 2024 Boyd dismissal news release
- official Downtown Library reopening page
- official local Form 803 filing in the San Rafael public-records portal

### Canonical result

- promote `actor-kate-colin`
- preserve `Mayor Kate Colin` as an observed label, not a separate actor
- accept a role claim tying Kate Colin to `inst-san-rafael-city-council` as `Mayor` on `2024-08-19`

### What not to promote

- no term start date from this evidence alone
- no district or election-seat inference from the meeting packet alone
- use the later official elected-official and election pages for the actual seat and current `SeatService` objects

## Example 2: Defense Block Security

### Raw observations

- `Defense Block Security`
- `Defense Block Security (DBS)`
- `DBS`

### Evidence

- official August 19, 2024 item `5.a` report
- official August 19, 2024 contract extract for the Defense Block Security exhibit
- later official San Rafael homelessness update pages

### Canonical result

- promote `actor-defense-block-security`
- preserve `DBS` as an alias
- allow later `Agreement`, `MoneyFlow`, and `Program` joins to target the same actor

### What not to promote

- no merge with any other private-security provider unless a later record makes that relationship explicit

## Example 3: Canal Alliance

### Raw observations

- `Canal Alliance`

### Evidence

- official December 19, 2022 San Rafael grants page naming Canal Alliance in a city resolution
- official August 19, 2024 packet text naming Canal Alliance as one of the referenced community organizations
- official Kate Colin Form 803 naming Canal Alliance as payee

### Canonical result

- promote `actor-canal-alliance`
- allow the same actor to connect to grants, city program references, and behested-payment flows

### What not to promote

- no staff, board, or advisory-role claims for Canal Alliance unless separate records support them

## Example 4: Mark Shotwell

### Raw observations

- `Mark Shotwell`
- `As the Chief Executive Officer of Ritter Center`

### Evidence

- official submitted public comment preserved in the August 19, 2024 meeting materials

### Canonical result

- promote `actor-mark-shotwell`
- promote `actor-ritter-center`
- accept an affiliation claim: `Mark Shotwell -> Ritter Center` with role label `Chief Executive Officer`

### What not to promote

- no broader tenure range from one public comment alone

## Current Boundary

The identity layer is strong enough now for:

- official-role joins
- contract counterparty joins
- basic nonprofit and filing-party joins

It is not strong enough yet for:

- blanket seat / district modeling for San Rafael councilmembers
- article-only identity resolution
- common-name person matching across weak sources
