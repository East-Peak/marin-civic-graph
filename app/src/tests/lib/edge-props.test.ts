// The relationship-property allowlist (registry/edge-properties.json) mirrored into TS by codegen, and the one
// sanitizer both serving modes run edge properties through.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { EDGE_PROPERTY_ALLOWLIST } from "@/lib/edge-properties.generated";
import {
  VOTE_LABEL,
  carriesEdgeProps,
  edgePropsProjection,
  sameEdgeProps,
  newEdgePropStats,
  sanitizeEdgeProps,
} from "@/lib/edge-props";
import { renderEdgeProperties } from "../../../scripts/codegen-edge-properties.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const REGISTRY_PATH = path.join(REPO_ROOT, "registry", "edge-properties.json");
const GENERATED_PATH = path.join(REPO_ROOT, "app", "src", "lib", "edge-properties.generated.ts");
const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8"));

const SENTINEL = "ledger_secret_code";

describe("edge-properties codegen mirror", () => {
  it("mirrors the registry exactly", () => {
    expect(EDGE_PROPERTY_ALLOWLIST).toEqual(registry.relationships);
    expect(EDGE_PROPERTY_ALLOWLIST).toEqual({
      CAST_VOTE: { vote: ["aye", "no", "abstain", "absent", "recused"] },
    });
  });

  it("the committed generated file is up to date", () => {
    expect(readFileSync(GENERATED_PATH, "utf-8")).toBe(renderEdgeProperties(registry));
  });

  it.each([
    [{ cast_vote: { vote: ["aye"] } }],
    [{ CAST_VOTE: { Vote: ["aye"] } }],
    [{ CAST_VOTE: { "vote}) RETURN 1 //": ["aye"] } }],
    [{ CAST_VOTE: { vote: [] } }],
    [{ CAST_VOTE: { vote: ["aye", "aye"] } }],
    [{ CAST_VOTE: { vote: ["it's"] } }],
  ])("refuses a malformed registry %j", (relationships) => {
    expect(() => renderEdgeProperties({ relationships })).toThrow();
  });
});

describe("sanitizeEdgeProps", () => {
  it("keeps an in-vocabulary vote and nothing else", () => {
    const stats = newEdgePropStats();
    expect(
      sanitizeEdgeProps(
        "CAST_VOTE",
        { vote: "recused", seat_id: "seat-x", seat_service_id: "ss-x", [SENTINEL]: "s3cret" },
        stats,
      ),
    ).toEqual({ vote: "recused" });
    expect(stats).toEqual({ dropped_out_of_vocabulary: 0, dropped_non_allowlisted: 3, suppressed_conflicting_duplicates: 0 });
  });

  it("drops and counts an out-of-vocabulary vote; the canonical empty form is undefined", () => {
    const stats = newEdgePropStats();
    expect(sanitizeEdgeProps("CAST_VOTE", { vote: "maybe-later" }, stats)).toBeUndefined();
    expect(sanitizeEdgeProps("CAST_VOTE", { vote: "AYE" }, stats)).toBeUndefined();
    expect(sanitizeEdgeProps("CAST_VOTE", { vote: 1 }, stats)).toBeUndefined();
    expect(stats).toEqual({ dropped_out_of_vocabulary: 3, dropped_non_allowlisted: 0, suppressed_conflicting_duplicates: 0 });
  });

  it("treats null, missing and non-object input as no properties, uncounted", () => {
    const stats = newEdgePropStats();
    expect(sanitizeEdgeProps("CAST_VOTE", { vote: null }, stats)).toBeUndefined();
    expect(sanitizeEdgeProps("CAST_VOTE", null, stats)).toBeUndefined();
    expect(sanitizeEdgeProps("CAST_VOTE", undefined, stats)).toBeUndefined();
    expect(sanitizeEdgeProps("CAST_VOTE", "{\"vote\":\"aye\"}", stats)).toBeUndefined();
    expect(sanitizeEdgeProps("CAST_VOTE", {}, stats)).toBeUndefined();
    expect(stats).toEqual({ dropped_out_of_vocabulary: 0, dropped_non_allowlisted: 0, suppressed_conflicting_duplicates: 0 });
  });

  it("gives other relationships nothing, even a valid-looking vote", () => {
    const stats = newEdgePropStats();
    expect(sanitizeEdgeProps("ATTENDED", { vote: "aye" }, stats)).toBeUndefined();
    expect(stats).toEqual({ dropped_out_of_vocabulary: 0, dropped_non_allowlisted: 1, suppressed_conflicting_duplicates: 0 });
  });

  it("works without a stats sink", () => {
    expect(sanitizeEdgeProps("CAST_VOTE", { vote: "aye" })).toEqual({ vote: "aye" });
  });
});

describe("edgePropsProjection", () => {
  it("projects each allowlisted property explicitly per relationship type, never properties(r)", () => {
    expect(edgePropsProjection("r")).toBe("CASE type(r) WHEN 'CAST_VOTE' THEN {vote: r.vote} ELSE null END");
    expect(edgePropsProjection("r")).not.toContain("properties(");
  });

  it("refuses a variable that is not a plain identifier", () => {
    expect(() => edgePropsProjection("r) RETURN 1 //")).toThrow();
  });
});

describe("VOTE_LABEL", () => {
  it("names each vote plainly; absent and recused never read as voting", () => {
    expect(VOTE_LABEL).toEqual({
      aye: "voted aye",
      no: "voted no",
      abstain: "abstained",
      absent: "absent",
      recused: "recused",
    });
    expect(VOTE_LABEL.absent).not.toMatch(/vot/);
    expect(VOTE_LABEL.recused).not.toMatch(/vot/);
  });
});

describe("duplicate relationships", () => {
  it("agree only when their public props are identical (missing equals missing)", () => {
    expect(sameEdgeProps({ vote: "aye" }, { vote: "aye" })).toBe(true);
    expect(sameEdgeProps(undefined, undefined)).toBe(true);
    expect(sameEdgeProps({ vote: "aye" }, { vote: "no" })).toBe(false);
    expect(sameEdgeProps({ vote: "absent" }, undefined)).toBe(false);
  });

  it("only allowlisted relationship types can carry props", () => {
    expect(carriesEdgeProps("CAST_VOTE")).toBe(true);
    expect(carriesEdgeProps("AT_MEETING")).toBe(false);
    expect(carriesEdgeProps("toString")).toBe(false);
  });
});
