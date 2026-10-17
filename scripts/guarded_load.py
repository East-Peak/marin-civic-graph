"""The no-overwrite load for crosswalk-required meeting sources.

The ordinary meeting load (load_neo4j_v2: `MERGE ... SET n += props`) rewrites every property it is
handed, so loading an adapter's view of a hand-curated meeting would replace its meeting_type, title,
display_label and promotion_state, and the shared institution/place stubs with it. A crosswalk-required
source (scripts/crosswalk.py) loads through here instead:

  * an existing node or relationship is never written: no property, label, display_label or
    promotion_state changes (differences are counted in the report, never applied);
  * the only writes are creates: new Meetings, new Records, and relationships touching a node created
    in the same load (an edge between two existing nodes is skipped and counted);
  * every Record id for an artifact comes from one resolver, for nodes and edges alike: the meeting's
    established Record of that kind (its url must not have changed), else an existing Record another
    meeting holds for the url (reused by a new meeting), else a new id from the template;
  * the graph is the memory for identity: a crosswalk target must be a Meeting of the institution whose
    page carries the slug; a meeting arriving native must not carry an existing meeting's slug;
  * anything else is a hold: the source writes NOTHING, and the report says why.

Reads and creates happen in one transaction (`GraphPort.transaction`). Writers serialize on the
ingestion run lock (scripts/run_lock.py); `CREATE` of an id that appeared meanwhile fails the id
uniqueness constraint and rolls everything back. `fakegraph:///<dir>` is a file-backed graph for
rehearsals and tests: an export as its seed plus an overlay of creates.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import crosswalk

NEW_NODE_TYPES = ("Meeting", "Record")
REQUIRED_CONSTRAINTS = ("Meeting", "Record")
LINK_EDGES = (("EVIDENCED_BY", "out"), ("RELATES_TO_MEETING", "in"))  # Meeting -> Record, Record -> Meeting
# Record types that are the same artifact as an adapter artifact (wave-01 used its own names).
ARTIFACT_KINDS = {
    "agenda": {"meeting_agenda", "agenda_pdf"},
    "packet": {"meeting_packet", "agenda_packet"},
    "minutes": {"meeting_minutes", "minutes_pdf", "minutes"},
    "video": {"meeting_video"},
    "captions": {"meeting_captions"},
    "mp3": {"meeting_audio"},
    "mp4": {"meeting_video_file"},
}
FAKE_SCHEME = "fakegraph"


class GraphWriteError(RuntimeError):
    """A create the graph refused (the id exists, a constraint is missing): the transaction rolled back."""


# --- graph ports -------------------------------------------------------------------------------------


@contextmanager
def open_port(uri: str, auth=None, database: str | None = None):
    """A graph port for `uri`: `fakegraph:///<abs dir>` (rehearsals, tests) or a Neo4j target."""
    parts = urlsplit(uri or "")
    if parts.scheme == FAKE_SCHEME:
        if parts.netloc or not parts.path.startswith("/"):
            raise ValueError(f"{uri!r}: a fake graph is fakegraph:///<absolute directory>")
        yield FakeGraphPort(Path(parts.path))
        return
    from neo4j_target import open_driver

    driver = open_driver(uri, auth=auth)
    try:
        yield Neo4jPort(driver, database)
    finally:
        driver.close()


class FakeGraphPort:
    """A graph in files: <dir>/seed (an export dir: nodes.jsonl, edges.jsonl; read only) + <dir>/overlay.jsonl.

    Export rows are `{id, labels, properties}` and `{start_id, type, end_id, properties}`, as
    export_live_graph.py writes them. Only creates ever reach the overlay, written atomically per
    transaction; creating an id that exists raises GraphWriteError.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._nodes: dict[str, dict] | None = None
        self._edges: list[dict] | None = None

    @classmethod
    def create(cls, path: Path, *, seed: Path) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=False)
        (path / "seed").symlink_to(Path(seed).resolve(), target_is_directory=True)
        (path / "overlay.jsonl").write_text("")
        return path

    def add_seed_node(self, node: dict) -> None:
        """Tests only: append a node to a seed this test wrote."""
        with open(self.path / "seed" / "nodes.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(node) + "\n")

    def overlay(self) -> tuple[list[dict], list[dict]]:
        rows = [json.loads(line) for line in (self.path / "overlay.jsonl").read_text().splitlines() if line]
        return [r["node"] for r in rows if "node" in r], [r["edge"] for r in rows if "edge" in r]

    def _load(self) -> None:
        if self._nodes is not None:
            return
        nodes, edges = {}, []
        for name in ("nodes.jsonl",):
            with open(self.path / "seed" / name, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        node = json.loads(line)
                        nodes[node["id"]] = node
        with open(self.path / "seed" / "edges.jsonl", encoding="utf-8") as fh:
            edges = [json.loads(line) for line in fh if line.strip()]
        overlay_nodes, overlay_edges = self.overlay()
        nodes.update({n["id"]: n for n in overlay_nodes})
        self._nodes, self._edges = nodes, edges + overlay_edges

    @contextmanager
    def transaction(self):
        self._load()
        tx = _FakeTx(self)
        yield tx
        if tx.rows:
            lines = (self.path / "overlay.jsonl").read_text() + "".join(json.dumps(r) + "\n" for r in tx.rows)
            fd, tmp = tempfile.mkstemp(dir=self.path, prefix=".overlay.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(lines)
            os.replace(tmp, self.path / "overlay.jsonl")
            self._nodes = self._edges = None

    # reads, shared by the transaction
    def nodes(self, ids) -> dict[str, dict]:
        self._load()
        return {i: {"labels": list(self._nodes[i]["labels"]), "props": dict(self._nodes[i]["properties"])}
                for i in ids if i in self._nodes}


class _FakeTx:
    def __init__(self, port: FakeGraphPort):
        self.port, self.rows = port, []

    def nodes(self, ids):
        return self.port.nodes(ids)

    def institution_meetings(self, institution_id: str) -> dict[str, str | None]:
        return {i: n["properties"].get("meeting_page_url") for i, n in self.port._nodes.items()
                if "Meeting" in n["labels"] and n["properties"].get("institution_id") == institution_id}

    def linked_records(self, meeting_ids) -> dict[str, set[str]]:
        wanted, found = set(meeting_ids), {m: set() for m in meeting_ids}
        records = {i for i, n in self.port._nodes.items() if "Record" in n["labels"]}
        for e in self.port._edges:
            if e["type"] == "EVIDENCED_BY" and e["start_id"] in wanted and e["end_id"] in records:
                found[e["start_id"]].add(e["end_id"])
            elif e["type"] == "RELATES_TO_MEETING" and e["end_id"] in wanted and e["start_id"] in records:
                found[e["end_id"]].add(e["start_id"])
        return found

    def existing_edges(self, triples) -> set[tuple[str, str, str]]:
        wanted = set(triples)
        return {(e["start_id"], e["type"], e["end_id"]) for e in self.port._edges} & wanted

    def create(self, nodes: list[dict], edges: list[dict]) -> None:
        taken = set(self.port._nodes)
        for node in nodes:
            if node["id"] in taken:
                raise GraphWriteError(f"{node['id']} already exists")
            taken.add(node["id"])
        for edge in edges:
            if edge["start_id"] not in taken or edge["end_id"] not in taken:
                raise GraphWriteError(f"edge endpoint missing: {edge['start_id']} -> {edge['end_id']}")
        self.rows += [{"node": n} for n in nodes] + [{"edge": e} for e in edges]


def _q(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


class Neo4jPort:
    """The real graph: one explicit transaction; labelled MATCH reads; CREATE-only writes."""

    def __init__(self, driver, database: str | None):
        self.driver, self.database = driver, database

    @contextmanager
    def transaction(self):
        from load_neo4j_v2 import _constrained_labels

        with self.driver.session(database=self.database) as session:
            labels = _constrained_labels(session)
            unique = _unique_id_labels(session)
            missing = [label for label in REQUIRED_CONSTRAINTS if label not in unique]
            if missing:
                raise GraphWriteError(f"no id uniqueness constraint on {', '.join(missing)}; refusing to write")
            tx = session.begin_transaction()
            try:
                yield _Neo4jTx(tx, labels)
                tx.commit()
            except BaseException:
                tx.rollback()
                raise
            finally:
                tx.close()


UNIQUE_CONSTRAINT_TYPES = ("UNIQUENESS", "NODE_PROPERTY_UNIQUENESS", "NODE_KEY")  # Neo4j 5.0 and later names


def _unique_id_labels(session) -> set[str]:
    """Labels whose `id` a node uniqueness (or node key) constraint protects: what makes CREATE fail closed."""
    rows = session.run("SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type, entityType")
    return {label for row in rows if row["entityType"] == "NODE" and row["type"] in UNIQUE_CONSTRAINT_TYPES
            and list(row["properties"] or []) == ["id"] for label in row["labelsOrTypes"] or []}


class _Neo4jTx:
    def __init__(self, tx, labels: list[str]):
        self.tx, self.labels = tx, labels

    def nodes(self, ids) -> dict[str, dict]:
        found, pending = {}, sorted(set(ids))
        for label in self.labels:
            if not pending:
                break
            rows = self.tx.run(f"UNWIND $ids AS id MATCH (n:{_q(label)} {{id: id}}) "
                               "RETURN n.id AS id, labels(n) AS labels, properties(n) AS props", ids=pending)
            for row in rows:
                found[row["id"]] = {"labels": list(row["labels"]), "props": dict(row["props"])}
            pending = [i for i in pending if i not in found]
        return found

    def institution_meetings(self, institution_id: str) -> dict[str, str | None]:
        rows = self.tx.run("MATCH (m:Meeting) WHERE m.institution_id = $inst "
                           "RETURN m.id AS id, m.meeting_page_url AS url", inst=institution_id)
        return {row["id"]: row["url"] for row in rows}

    def linked_records(self, meeting_ids) -> dict[str, set[str]]:
        ids = sorted(set(meeting_ids))
        found = {m: set() for m in ids}
        for query in ("UNWIND $ids AS id MATCH (:Meeting {id: id})-[:EVIDENCED_BY]->(r:Record) "
                      "RETURN id, r.id AS record",
                      "UNWIND $ids AS id MATCH (r:Record)-[:RELATES_TO_MEETING]->(:Meeting {id: id}) "
                      "RETURN id, r.id AS record"):
            for row in self.tx.run(query, ids=ids):
                found[row["id"]].add(row["record"])
        return found

    def existing_edges(self, triples) -> set[tuple[str, str, str]]:
        triples = sorted(set(triples))
        label_of = {i: n["labels"][0] for i, n in self.nodes({x for s, _, t in triples for x in (s, t)}).items()}
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for s, rel, t in triples:
            if s in label_of and t in label_of:
                groups.setdefault((label_of[s], rel, label_of[t]), []).append({"s": s, "t": t})
        found = set()
        for (sl, rel, tl), pairs in groups.items():
            rows = self.tx.run(f"UNWIND $pairs AS p MATCH (s:{_q(sl)} {{id: p.s}})-[:{_q(rel)}]->(t:{_q(tl)} "
                               "{id: p.t}) RETURN DISTINCT p.s AS s, p.t AS t", pairs=pairs)
            found |= {(row["s"], rel, row["t"]) for row in rows}
        return found

    def create(self, nodes: list[dict], edges: list[dict]) -> None:
        by_labels: dict[tuple[str, ...], list[dict]] = {}
        for node in nodes:
            by_labels.setdefault(tuple(node["labels"]), []).append(node)
        for labels, group in by_labels.items():
            batch = [{"id": n["id"], "props": n["properties"]} for n in group]
            created = self.tx.run(f"UNWIND $batch AS row CREATE (n:{':'.join(_q(x) for x in labels)}) "
                                  "SET n = row.props RETURN count(n) AS n", batch=batch).single()["n"]
            if created != len(batch):
                raise GraphWriteError(f"created {created} of {len(batch)} {labels} nodes")
        label_of = {n["id"]: n["labels"][0] for n in nodes}
        label_of.update({i: n["labels"][0] for i, n in self.nodes(
            {x for e in edges for x in (e["start_id"], e["end_id"])} - set(label_of)).items()})
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for e in edges:
            groups.setdefault((label_of[e["start_id"]], e["type"], label_of[e["end_id"]]), []).append(e)
        for (sl, rel, tl), group in groups.items():
            batch = [{"s": e["start_id"], "t": e["end_id"], "props": e["properties"]} for e in group]
            created = self.tx.run(f"UNWIND $batch AS row MATCH (s:{_q(sl)} {{id: row.s}}) MATCH (t:{_q(tl)} "
                                  f"{{id: row.t}}) CREATE (s)-[r:{_q(rel)}]->(t) SET r = row.props "
                                  "RETURN count(r) AS n", batch=batch).single()["n"]
            if created != len(batch):
                raise GraphWriteError(f"created {created} of {len(batch)} {rel} edges")


# --- the load ------------------------------------------------------------------------------------------


class _Holds(list):
    def add(self, reason: str, **detail) -> None:
        self.append({"reason": reason, **detail})


def record_template(source_id: str, meeting_id: str, art: str) -> str:
    """The id a new artifact Record takes: the convention every meeting source already uses."""
    return f"record-{source_id}-{meeting_id.split('meeting-', 1)[-1]}-{art}"


def _artifacts(meeting: dict) -> dict[str, str]:
    return {art: a["url"] for art, a in (meeting.get("artifacts") or {}).items() if a.get("available") and a.get("url")}


def _check_policy(capture: dict, config: dict, root: Path, holds: _Holds):
    header = capture.get("crosswalk")
    if not crosswalk.required(config) or not isinstance(header, dict) or header.get("path") != config.get("crosswalk"):
        holds.add("policy_mismatch", detail="the capture's crosswalk header and the registry's identity disagree")
        return None
    try:
        xw = crosswalk.load(root / config["crosswalk"], config["id"])
    except crosswalk.CrosswalkError as exc:
        holds.add("crosswalk_invalid", detail=str(exc))
        return None
    if xw.sha256 != header.get("sha256"):
        holds.add("crosswalk_changed", detail=f"staged with {header.get('sha256')}, now {xw.sha256}")
        return None
    return xw


def _check_meetings(tx, capture: dict, config: dict, xw, holds: _Holds) -> dict[str, dict]:
    """canonical id -> {meeting, slug, existing}; holds for every identity the graph contradicts."""
    sid, inst = config["id"], config["institution_id"]
    pages = tx.institution_meetings(inst)
    slug_owner: dict[str, str] = {}
    for mid, url in pages.items():
        if crosswalk.page_slug(url):
            slug_owner.setdefault(crosswalk.page_slug(url), mid)
    meetings = capture.get("meetings") or []
    canon = [m.get("meeting_id") for m in meetings]
    adapter = [m.get("adapter_meeting_id") for m in meetings]
    existing = tx.nodes([*canon, *adapter])
    out = {}
    for m, mid, own in zip(meetings, canon, adapter):
        try:
            slug = crosswalk.slug_of(sid, own)
        except crosswalk.CrosswalkError as exc:
            holds.add("crosswalk_disagrees", meeting=mid, detail=str(exc))
            continue
        if xw.entries.get(slug, own) != mid:
            holds.add("crosswalk_disagrees", meeting=mid, detail=f"{slug} resolves to {xw.entries.get(slug, own)}")
            continue
        node = existing.get(mid)
        if mid != own:
            props = (node or {}).get("props", {})
            if not (node and "Meeting" in node["labels"] and props.get("institution_id") == inst
                    and crosswalk.page_slug(props.get("meeting_page_url")) == slug):
                holds.add("crosswalk_target_mismatch", meeting=mid, slug=slug,
                          detail="the target is not this institution's Meeting whose page carries the slug")
                continue
            if own in existing:
                holds.add("duplicate_native_meeting", meeting=mid, native=own)
                continue
        elif node is None and slug_owner.get(slug) not in (None, mid):
            holds.add("crosswalk_entry_missing", meeting=mid, slug=slug, existing=slug_owner[slug])
            continue
        out[mid] = {"meeting": m, "slug": slug, "existing": node is not None}
    return out


def _resolve_records(tx, source_id: str, meetings: dict[str, dict], institution_id: str,
                     holds: _Holds) -> dict[tuple[str, str], str]:
    """(meeting id, art) -> Record id, for every available artifact; holds where identity is unclear."""
    every = list(tx.institution_meetings(institution_id))
    linked = tx.linked_records(every)
    records = tx.nodes({r for rs in linked.values() for r in rs})
    by_url: dict[str, set[str]] = {}
    for rid, node in records.items():
        if node["props"].get("source_url"):
            by_url.setdefault(node["props"]["source_url"], set()).add(rid)
    templates = tx.nodes({record_template(source_id, mid, art) for mid, x in meetings.items()
                          for art in _artifacts(x["meeting"])})
    resolved: dict[tuple[str, str], str] = {}
    fresh: dict[str, list[tuple[str, str]]] = {}  # url -> [(meeting, art)] needing a new Record
    for mid, x in sorted(meetings.items()):
        arts = _artifacts(x["meeting"])
        if len(set(arts.values())) != len(arts):
            holds.add("artifact_url_shared", meeting=mid, detail="two artifacts of one meeting share a url")
            continue
        mine = {r: records[r] for r in linked.get(mid, ()) if r in records}
        for art, url in sorted(arts.items()):
            template = record_template(source_id, mid, art)
            kinds = ARTIFACT_KINDS.get(art, {f"meeting_{art}"})
            established = {r for r, n in mine.items() if n["props"].get("record_type") in kinds}
            props_of = {**{r: n["props"] for r, n in mine.items()},
                        **{r: n["props"] for r, n in templates.items()}}
            if template in templates:
                established.add(template)
            if established:
                only = next(iter(established))
                if len(established) == 1 and props_of[only].get("source_url") == url:
                    resolved[(mid, art)] = only
                else:
                    holds.add("artifact_url_changed", meeting=mid, art=art, url=url,
                              established={r: props_of[r].get("source_url") for r in sorted(established)})
                continue
            others = sorted(by_url.get(url, ()))
            if others:
                if not x["existing"] and len(others) == 1 and records[others[0]]["props"].get("record_type") in kinds:
                    resolved[(mid, art)] = others[0]
                else:
                    holds.add("artifact_url_on_other_record", meeting=mid, art=art, url=url, records=others)
                continue
            fresh.setdefault(url, []).append((mid, art))
    for url, users in fresh.items():
        if len({art for _, art in users}) > 1:
            holds.add("artifact_url_shared_across_kinds", url=url, users=sorted(map(list, users)))
            continue
        owner = min(users)
        for user in users:
            resolved[user] = record_template(source_id, *owner)
    return resolved


def load_capture(graph, capture: dict, config: dict, *, root: Path) -> dict:
    """Load one capture without overwriting anything; returns the load report (outcome loaded | held)."""
    from normalize_meetings import normalize_rows

    holds = _Holds()
    report = {"source_id": config["id"], "capture_id": capture.get("capture_id"),
              "crosswalk_sha256": (capture.get("crosswalk") or {}).get("sha256"), "holds": holds,
              "created": {"nodes": {}, "edges": []}, "unchanged": {"nodes": 0, "edges": 0},
              "skipped_edges": {}, "protected_differences": {}}
    xw = _check_policy(capture, config, Path(root), holds)
    if xw is None:
        return {**report, "outcome": "held"}
    with graph.transaction() as tx:
        meetings = _check_meetings(tx, capture, config, xw, holds)
        resolved = _resolve_records(tx, config["id"], meetings, config["institution_id"], holds)
        if holds:
            return {**report, "outcome": "held"}
        nodes, edges = normalize_rows(
            capture, record_id=lambda m, art: resolved[(m["meeting_id"], art)],
            meeting_props=lambda m: {"meeting_page_url": m["source_url"]} if m.get("source_url") else {})
        plan = _plan(tx, nodes, edges, holds)
        if holds:
            return {**report, "outcome": "held"}
        tx.create(plan["nodes"], plan["edges"])
    created_nodes: dict[str, list[str]] = {}
    for node in plan["nodes"]:
        created_nodes.setdefault(node["labels"][0], []).append(node["id"])
    return {**report, "outcome": "loaded", "normalized": {"nodes": nodes, "edges": edges},
            "created": {"nodes": created_nodes,
                        "edges": [[e["start_id"], e["type"], e["end_id"]] for e in plan["edges"]]},
            "unchanged": plan["unchanged"], "skipped_edges": dict(plan["skipped"]),
            "protected_differences": dict(plan["differences"])}


def _export_row(node: dict) -> dict:
    """A normalized node as the graph stores it: display_label and promotion_state are properties."""
    props = {k: v for k, v in node["properties"].items() if k != "payload_json" and v is not None}  # Neo4j stores no nulls
    return {"id": node["id"], "labels": list(node["labels"]),
            "properties": {**props, "id": node["id"], "display_label": node.get("display_label", ""),
                           "promotion_state": node.get("promotion_state", "")}}


def _plan(tx, nodes: list[dict], edges: list[dict], holds: _Holds) -> dict:
    rows: dict[str, dict] = {}
    for node in nodes:
        rows.setdefault(node["id"], _export_row(node))  # a shared Record: one row
    existing = tx.nodes(rows)
    create, differences = [], Counter()
    for nid, row in rows.items():
        if nid in existing:
            have = existing[nid]["props"]
            label = row["labels"][0]
            differences.update(f"{label}.{k}" for k, v in row["properties"].items() if have.get(k) != v)
        elif row["labels"][0] in NEW_NODE_TYPES:
            create.append(row)
        else:
            holds.add("missing_node", node=nid, detail=f"{row['labels'][0]} is not created by this load")
    created = {row["id"] for row in create}
    triples = {(e["source_id"], e["relationship_type"], e["target_id"]): e for e in edges}
    present = tx.existing_edges([t for t in triples if t[0] in existing and t[2] in existing])
    new_edges, skipped, unchanged = [], Counter(), 0
    for (s, rel, t), edge in triples.items():
        if (s, rel, t) in present:
            unchanged += 1
        elif s in created or t in created:
            new_edges.append({"start_id": s, "type": rel, "end_id": t, "properties": dict(edge.get("properties") or {})})
        elif s in existing and t in existing:
            skipped[rel] += 1
        else:
            holds.add("missing_node", edge=[s, rel, t])
    return {"nodes": create, "edges": new_edges, "skipped": skipped, "differences": differences,
            "unchanged": {"nodes": len(rows) - len(create), "edges": unchanged}}
