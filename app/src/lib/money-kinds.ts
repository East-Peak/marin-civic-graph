// What kind of money a total is. The bake (scripts/bake_public_substrate.py MONEY_KINDS) classifies every
// MoneyFlow; pages show each kind on its own line and never add kinds together: a county contract amount is the
// contract's amount, not money paid, and campaign money is what filers reported.

export const MONEY_KIND_ORDER = [
  "county_contract",
  "authorization",
  "campaign_contribution",
  "campaign_spending",
  "behested_payment",
  "other",
] as const;

export type MoneyKind = (typeof MONEY_KIND_ORDER)[number];

type KindText = {
  title: string;
  note: string;
  inWord: string;
  outWord: string;
  counterparty: string;
};

export const MONEY_KIND_TEXT: Record<MoneyKind, KindText> = {
  county_contract: {
    title: "County contract amounts",
    note: "contract amounts, not payments",
    inWord: "contract",
    outWord: "contract awarded",
    counterparty: "county contract",
  },
  authorization: {
    title: "Approved amounts",
    note: "authorizations, not payments",
    inWord: "approved",
    outWord: "approved",
    counterparty: "approved amount",
  },
  campaign_contribution: {
    title: "Campaign contributions",
    note: "as reported on filings",
    inWord: "received",
    outWord: "given",
    counterparty: "contribution",
  },
  campaign_spending: {
    title: "Campaign spending",
    note: "as reported on filings",
    inWord: "paid by campaigns",
    outWord: "spent",
    counterparty: "campaign spending",
  },
  behested_payment: {
    title: "Behested payments",
    note: "as reported",
    inWord: "received",
    outWord: "made",
    counterparty: "behested payment",
  },
  other: {
    title: "Other recorded amounts",
    note: "kind not recorded",
    inWord: "in",
    outWord: "out",
    counterparty: "other",
  },
};

export function isMoneyKind(value: unknown): value is MoneyKind {
  return typeof value === "string" && (MONEY_KIND_ORDER as readonly string[]).includes(value);
}
