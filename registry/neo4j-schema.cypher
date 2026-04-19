// Neo4j Schema for Marin Civic Graph
// Auto-generated for the settled 21-type ontology
// IMPORTANT: Run this schema BEFORE loading any data into the database
// This file creates unique constraints, full-text indexes, and property indexes
// for optimal query performance and data integrity.

// ============================================================================
// Unique Constraints (21 core node types + 1 QA)
// ============================================================================
// Each node type requires a unique constraint on its id property
// These ensure data integrity and provide fast lookups by entity ID

CREATE CONSTRAINT person_id_unique IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT organization_id_unique IF NOT EXISTS FOR (n:Organization) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT committee_id_unique IF NOT EXISTS FOR (n:Committee) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT seat_id_unique IF NOT EXISTS FOR (n:Seat) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT seatservice_id_unique IF NOT EXISTS FOR (n:SeatService) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT election_id_unique IF NOT EXISTS FOR (n:Election) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT candidacy_id_unique IF NOT EXISTS FOR (n:Candidacy) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT meeting_id_unique IF NOT EXISTS FOR (n:Meeting) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT agendaitem_id_unique IF NOT EXISTS FOR (n:AgendaItem) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT decision_id_unique IF NOT EXISTS FOR (n:Decision) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT filing_id_unique IF NOT EXISTS FOR (n:Filing) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT moneyflow_id_unique IF NOT EXISTS FOR (n:MoneyFlow) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (n:Case) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT proceeding_id_unique IF NOT EXISTS FOR (n:Proceeding) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT project_id_unique IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT program_id_unique IF NOT EXISTS FOR (n:Program) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT agreement_id_unique IF NOT EXISTS FOR (n:Agreement) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT amendment_id_unique IF NOT EXISTS FOR (n:Amendment) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT record_id_unique IF NOT EXISTS FOR (n:Record) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT place_id_unique IF NOT EXISTS FOR (n:Place) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT issue_id_unique IF NOT EXISTS FOR (n:Issue) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT validationcheck_id_unique IF NOT EXISTS FOR (n:ValidationCheck) REQUIRE n.id IS UNIQUE;

// ============================================================================
// Full-text Indexes
// ============================================================================
// Full-text indexes enable efficient keyword searches across entity names
// Covers primary searchable entity types and display labels

CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:Person|Organization|Committee|Project|Program|Case|Agreement)
ON EACH [n.name, n.display_label];

// ============================================================================
// Property Indexes for Query Performance
// ============================================================================
// Property indexes optimize filtering and sorting by commonly queried attributes
// Includes temporal indexes (dates) and categorical indexes (types)

CREATE INDEX meeting_date IF NOT EXISTS FOR (n:Meeting) ON (n.meeting_date);
CREATE INDEX decision_decided_at IF NOT EXISTS FOR (n:Decision) ON (n.decided_at);
CREATE INDEX moneyflow_flow_date IF NOT EXISTS FOR (n:MoneyFlow) ON (n.flow_date);
CREATE INDEX moneyflow_amount IF NOT EXISTS FOR (n:MoneyFlow) ON (n.amount);
CREATE INDEX filing_signed_at IF NOT EXISTS FOR (n:Filing) ON (n.signed_at);
CREATE INDEX filing_filed_at IF NOT EXISTS FOR (n:Filing) ON (n.filed_at);
CREATE INDEX election_date IF NOT EXISTS FOR (n:Election) ON (n.election_date);
CREATE INDEX proceeding_date IF NOT EXISTS FOR (n:Proceeding) ON (n.date);
CREATE INDEX agreement_effective_date IF NOT EXISTS FOR (n:Agreement) ON (n.effective_date);
CREATE INDEX moneyflow_flow_type IF NOT EXISTS FOR (n:MoneyFlow) ON (n.flow_type);
CREATE INDEX filing_filing_type IF NOT EXISTS FOR (n:Filing) ON (n.filing_type);
CREATE INDEX decision_decision_type IF NOT EXISTS FOR (n:Decision) ON (n.decision_type);

// ============================================================================
// Open Marin search index (spec §3.3)
// ============================================================================
// Composite full-text index spanning all 15 searchable types.
// One query hits every indexed type; Record ranked into a separate bucket client-side.

CREATE FULLTEXT INDEX openmarin_search_index IF NOT EXISTS
FOR (n:Person|Organization|Committee|Decision|Project|Program|Case|Meeting|Filing|Agreement|Amendment|Election|Place|Issue|Record)
ON EACH [n.search_label, n.search_terms];

// Per-type search_rank property indexes keep per-type filtering cheap.
CREATE INDEX person_search_rank IF NOT EXISTS FOR (n:Person) ON (n.search_rank);
CREATE INDEX organization_search_rank IF NOT EXISTS FOR (n:Organization) ON (n.search_rank);
CREATE INDEX committee_search_rank IF NOT EXISTS FOR (n:Committee) ON (n.search_rank);
CREATE INDEX decision_search_rank IF NOT EXISTS FOR (n:Decision) ON (n.search_rank);
CREATE INDEX project_search_rank IF NOT EXISTS FOR (n:Project) ON (n.search_rank);
CREATE INDEX program_search_rank IF NOT EXISTS FOR (n:Program) ON (n.search_rank);
CREATE INDEX case_search_rank IF NOT EXISTS FOR (n:Case) ON (n.search_rank);
CREATE INDEX meeting_search_rank IF NOT EXISTS FOR (n:Meeting) ON (n.search_rank);
CREATE INDEX filing_search_rank IF NOT EXISTS FOR (n:Filing) ON (n.search_rank);
CREATE INDEX agreement_search_rank IF NOT EXISTS FOR (n:Agreement) ON (n.search_rank);
CREATE INDEX amendment_search_rank IF NOT EXISTS FOR (n:Amendment) ON (n.search_rank);
CREATE INDEX election_search_rank IF NOT EXISTS FOR (n:Election) ON (n.search_rank);
CREATE INDEX place_search_rank IF NOT EXISTS FOR (n:Place) ON (n.search_rank);
CREATE INDEX issue_search_rank IF NOT EXISTS FOR (n:Issue) ON (n.search_rank);
CREATE INDEX record_search_rank IF NOT EXISTS FOR (n:Record) ON (n.search_rank);
