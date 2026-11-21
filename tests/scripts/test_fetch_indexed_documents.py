"""Minutes coverage: the frozen inventory, the probe/bulk fetcher and its attempted-URL ledger (mocked network,
fictional meetings and text)."""
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fetch_indexed_documents as fid  # noqa: E402
import minutes_transport as mt  # noqa: E402

PDF = b"%PDF-1.4 fictional minutes of the Pinewood council"
HTML = b"<html><body>Fictional minutes of the Pinewood Council</body></html>"
NOV, FX, BV, ROSS, SR = ("novato-city-council", "fairfax-town-council", "belvedere-city-council",
                         "ross-town-council", "san-rafael-city-council")
GCS = "https://storage.googleapis.com"
ALLOW_ALL = (200, b"User-agent: *\nDisallow:\n", {"content-type": "text/plain"})
SATURDAY = dt.datetime(2030, 1, 5, 10, 0)


def nov_url(n):
    return f"https://novato.granicus.com/MinutesViewer.php?clip_id={n}"


def fx_url(slug):
    return f"{GCS}/proudcity/fairfaxca/uploads/2030/01/{slug}.pdf"


MEETINGS = [  # (meeting id, date, title, minutes URL or None = a Record without one)
    (f"meeting-{NOV}-1", "2030-01-01", "City Council", "//novato.granicus.com/MinutesViewer.php?clip_id=1"),
    (f"meeting-{NOV}-2", "2030-01-08", "City Council", nov_url(2)),
    (f"meeting-{NOV}-3", "2030-01-15", "City Council", nov_url(3)),
    (f"meeting-{NOV}-4", "2030-01-22", "Planning Commission", nov_url(4)),
    (f"meeting-{NOV}-5", "2030-01-29", "City Council", nov_url(5)),
    (f"meeting-{FX}-town-council-meeting-january-3-2030", "2030-01-03", "Town Council Meeting: January 3, 2030",
     fx_url("a")),
    (f"meeting-{FX}-town-council-meeting-january-17-2030", "2030-01-17", "Town Council Meeting: January 17, 2030",
     f"{GCS}/proudcity/2030/01/b.pdf"),
    (f"meeting-{BV}-city-council-meeting-january-9-2030", "2030-01-09", "City Council Meeting: January 9, 2030",
     f"{GCS}/proudcity/belvedereca/2030/01/c.pdf"),
    (f"meeting-{ROSS}-2030-01-10-row-3", "2030-01-10", "Ross Town Council Meeting",
     "https://www.townofrossca.gov/sites/default/files/fileattachments/town_council/meeting/9/d.pdf"),
    (f"meeting-{SR}-city-council-january-6-2030", "2030-01-06", "City Council", None),
    ("meeting-2030-01-06-san-rafael-city-council", "2030-01-06", "San Rafael City Council meeting", None),
]


def make_substrate(path, meetings=MEETINGS, extra=()):
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, search_label TEXT, props TEXT);"
                     "CREATE TABLE edges (source TEXT, rel TEXT, target TEXT, props TEXT);"
                     "CREATE TABLE meta (key TEXT, value TEXT);")
    db.execute("INSERT INTO meta VALUES ('as_of_date', '2030-02-01')")
    for mid, date, title, url in list(meetings) + list(extra):
        db.execute("INSERT INTO nodes VALUES (?, 'Meeting', '', ?)",
                   (mid, json.dumps({"meeting_date": date, "title": title})))
        rid = f"record-{mid}-minutes"
        props = {"record_type": "meeting_minutes"} | ({"preferred_public_url": url} if url else {})
        db.execute("INSERT INTO nodes VALUES (?, 'Record', '', ?)", (rid, json.dumps(props)))
        db.execute("INSERT INTO edges VALUES (?, 'EVIDENCED_BY', ?, NULL)", (mid, rid))
    db.commit()
    db.close()
    return path


class Net:
    def __init__(self, responses):
        self.responses, self.t, self.calls = dict(responses), 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def http(self, url, headers):
        self.calls.append((self.t, url))
        self.t += 0.1
        r = self.responses.get(url, (404, b"gone", {}))
        if isinstance(r, Exception):
            raise r
        return r

    def urls(self):
        return [u for _, u in self.calls]


@pytest.fixture
def world(tmp_path):
    raw, staging = tmp_path / "raw", tmp_path / "staging"
    sub = make_substrate(tmp_path / "sub.sqlite")
    (raw / NOV / "minutes").mkdir(parents=True)
    (raw / NOV / "minutes" / f"meeting-{NOV}-1.pdf").write_bytes(PDF)  # cached before the goal
    inv = fid.freeze_inventory(sub, raw, staging)
    return {"raw": raw, "staging": staging, "sub": sub, "inv": inv}


def run(world, net, source, mode="bulk", **kw):
    transport = mt.Transport(world["raw"], http=net.http, sleep=net.sleep, now=net.now)
    return fid.fetch_source(world["inv"], source, world["raw"], mode=mode, transport=transport,
                            clock=lambda: SATURDAY, **kw)


def ledger(world, source):
    path = world["raw"] / source / fid.FETCH_LOG
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


# --- the inventory ------------------------------------------------------------------------------------------------

def test_the_inventory_freezes_every_minutes_meeting_with_its_sha(world):
    inv = json.loads(world["inv"].read_text())
    ids = [c["meeting_id"] for c in inv["candidates"]]
    assert sorted(ids) == sorted(m[0] for m in MEETINGS) and len(ids) == len(set(ids))
    assert (world["inv"].parent / (world["inv"].name + ".sha256")).read_text().split()[0] == fid.sha256_file(
        world["inv"])
    by = {c["meeting_id"]: c for c in inv["candidates"]}
    assert by[f"meeting-{NOV}-1"]["url"] == nov_url(1) and by[f"meeting-{NOV}-1"]["cached"] == f"meeting-{NOV}-1.pdf"
    assert by[f"meeting-{NOV}-4"]["body"] == "Novato Planning Commission"
    assert by["meeting-2030-01-06-san-rafael-city-council"]["source"] == SR
    assert by["meeting-2030-01-06-san-rafael-city-council"]["url"] is None
    assert inv["counts"][SR] == {"candidates": 2, "no-url": 2, "cached": 0, "to-fetch": 0}
    assert inv["counts"][NOV] == {"candidates": 5, "no-url": 0, "cached": 1, "to-fetch": 4}


def test_the_inventory_lists_minutes_meetings_no_source_holds(tmp_path):
    sub = make_substrate(tmp_path / "s.sqlite", extra=[("meeting-larkspur-city-council-9", "2030-01-01", "x",
                                                        "https://larkspur.example/m.pdf")])
    inv = json.loads(fid.freeze_inventory(sub, tmp_path / "raw", tmp_path / "st").read_text())
    assert inv["unassigned"] == ["meeting-larkspur-city-council-9"]


def test_a_changed_inventory_is_refused(world):
    data = json.loads(world["inv"].read_text())
    data["candidates"].pop()
    world["inv"].write_text(json.dumps(data))
    with pytest.raises(fid.FetchError, match="sha256"):
        run(world, Net({}), NOV)


# --- probe and bulk -----------------------------------------------------------------------------------------------

def test_probe_takes_at_most_three_and_records_the_chain(world):
    hop = "https://novato.granicus.com/DocumentViewer.php?file=x.pdf"
    net = Net({nov_url(5): (302, b"", {"location": hop}), hop: (200, PDF, {}), nov_url(4): (200, HTML, {}),
               nov_url(3): (200, PDF, {}), nov_url(2): (200, PDF, {})})
    res = run(world, net, NOV, mode="probe")
    assert res.attempted == 3 and net.urls() == [nov_url(5), hop, nov_url(4), nov_url(3)]
    first = ledger(world, NOV)[0]
    assert first["chain"] == [{"url": nov_url(5), "status": 302, "location": hop},
                              {"url": hop, "status": 200, "location": None}]
    assert first["state"] == "fetched" and first["mode"] == "probe" and first["final_url"] == hop
    assert (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-4.html").read_bytes() == HTML


def test_bulk_fetches_everything_left_and_writes_an_index_readable_ledger(world):
    net = Net({nov_url(n): (200, PDF + str(n).encode(), {}) for n in (2, 3, 4, 5)})
    res = run(world, net, NOV)
    assert res.attempted == 4 and res.stop is None
    rows = ledger(world, NOV)
    assert {r["meeting_id"] for r in rows} == {f"meeting-{NOV}-{n}" for n in (2, 3, 4, 5)}
    for r in rows:
        data = (world["raw"] / NOV / "minutes" / r["path"]).read_bytes()
        assert r["status"] == "ok" and r["state"] == "fetched" and r["fetched_at"]
        assert r["sha256"] == fid.sha256_bytes(data)
    assert nov_url(1) not in net.urls()  # cached before the goal: never requested
    states = fid.candidate_states(world["inv"], world["raw"])
    assert states["counts"][NOV] == {"already-cached": 1, "fetched": 4}


def test_a_failed_url_is_never_retried(world):
    net = Net({nov_url(5): (404, b"", {}), nov_url(4): OSError("reset"), nov_url(3): (200, b"plain text", {}),
               nov_url(2): (200, PDF, {})})
    run(world, net, NOV)
    reasons = {r["meeting_id"]: (r["state"], r["reason"]) for r in ledger(world, NOV)}
    assert reasons[f"meeting-{NOV}-5"] == ("failed", "HTTP 404")
    assert reasons[f"meeting-{NOV}-4"][0] == "failed" and "reset" in reasons[f"meeting-{NOV}-4"][1]
    assert reasons[f"meeting-{NOV}-3"] == ("failed", "response is not a PDF, HTML or DOCX document")
    again = Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)})
    assert run(world, again, NOV).attempted == 0 and again.calls == []


def test_an_unknown_redirect_target_is_logged_and_not_requested(world):
    elsewhere = "https://files.elsewhere.example/minutes/5.pdf"
    net = Net({nov_url(5): (302, b"", {"location": elsewhere}), elsewhere: (200, PDF, {})})
    run(world, net, NOV, limit=1)
    row = ledger(world, NOV)[0]
    assert elsewhere not in net.urls()
    assert row["state"] == "failed" and elsewhere in row["reason"] and "not requested" in row["reason"]
    assert row["chain"][-1] == {"url": nov_url(5), "status": 302, "location": elsewhere}


def test_a_redirect_to_an_off_limits_host_is_never_requested(world):
    wall = "https://www.novato.gov/minutes/5.pdf"
    net = Net({nov_url(5): (302, b"", {"location": wall})})
    run(world, net, NOV, limit=1)
    assert wall not in net.urls() and ledger(world, NOV)[0]["state"] == "failed"


def test_an_initial_url_outside_the_allow_list_is_excluded_without_a_request(world):
    net = Net({f"{GCS}/robots.txt": ALLOW_ALL, fx_url("a"): (200, PDF, {})})
    run(world, net, FX)
    by = {r["meeting_id"]: r for r in ledger(world, FX)}
    no_folder = by[f"meeting-{FX}-town-council-meeting-january-17-2030"]
    assert no_folder["state"] == "excluded-by-authorization" and "allow-list" in no_folder["reason"]
    assert f"{GCS}/proudcity/2030/01/b.pdf" not in net.urls()
    assert by[f"meeting-{FX}-town-council-meeting-january-3-2030"]["state"] == "fetched"
    assert (world["raw"] / FX / "minutes" / f"meeting-{FX}-town-council-meeting-january-3-2030.pdf").exists()


def test_robots_disallow_excludes_by_authorization(world):
    net = Net({f"{GCS}/robots.txt": (200, b"User-agent: *\nDisallow: /proudcity/belvedereca/\n", {}),
               f"{GCS}/proudcity/belvedereca/2030/01/c.pdf": (200, PDF, {})})
    run(world, net, BV)
    row = ledger(world, BV)[0]
    assert row["state"] == "excluded-by-authorization" and "Disallow: /proudcity/belvedereca/" in row["reason"]
    assert net.urls() == [f"{GCS}/robots.txt"]


def test_a_stop_ends_the_source_and_every_later_run_on_its_family(world):
    net = Net({nov_url(5): (200, PDF, {}), nov_url(4): (429, b"", {})})
    res = run(world, net, NOV)
    assert res.stop and res.attempted == 2 and nov_url(3) not in net.urls()
    assert json.loads((world["raw"] / mt.STOPS_FILE).read_text())["stops"][0]["host_family"] == "granicus.com"
    later = Net({nov_url(n): (200, PDF, {}) for n in (2, 3)})
    res2 = run(world, later, NOV)
    assert later.calls == [] and res2.attempted == 0 and "stop record" in res2.skipped
    states = fid.candidate_states(world["inv"], world["raw"])
    assert states["counts"][NOV] == {"already-cached": 1, "fetched": 1, "failed": 1, "unattempted-after-stop": 2}


def test_states_reconcile_to_the_inventory(world):
    run(world, Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)}), NOV)
    run(world, Net({f"{GCS}/robots.txt": ALLOW_ALL, fx_url("a"): (200, PDF, {})}), FX)
    states = fid.candidate_states(world["inv"], world["raw"])
    inv = json.loads(world["inv"].read_text())
    assert sum(sum(c.values()) for c in states["counts"].values()) == len(inv["candidates"])
    assert states["counts"][SR] == {"no-url": 2}
    assert states["counts"][BV] == {"pending": 1}  # never run: not yet a terminal state
    assert set(fid.STATES) >= {s for c in states["counts"].values() for s in c} - {"pending"}


def test_one_url_under_two_meetings_is_requested_once(tmp_path):
    shared = nov_url(9)
    sub = make_substrate(tmp_path / "s.sqlite", meetings=[
        (f"meeting-{NOV}-8", "2030-01-01", "City Council", shared),
        (f"meeting-{NOV}-9", "2030-01-02", "City Council", shared)])
    raw = tmp_path / "raw"
    w = {"raw": raw, "inv": fid.freeze_inventory(sub, raw, tmp_path / "st")}
    net = Net({shared: (200, PDF, {})})
    run(w, net, NOV)
    assert net.urls() == [shared]
    rows = ledger(w, NOV)
    assert [r["state"] for r in rows] == ["fetched", "fetched"] and "no request" in rows[1]["reason"]
    assert (raw / NOV / "minutes" / f"meeting-{NOV}-8.pdf").read_bytes() == PDF


def test_an_existing_file_is_never_overwritten(world):
    (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-5.pdf").write_bytes(b"%PDF-1.4 someone saved this by hand")
    net = Net({nov_url(5): (200, PDF, {})})
    run(world, net, NOV, limit=1)
    assert nov_url(5) not in net.urls()
    assert (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-5.pdf").read_bytes().endswith(b"by hand")


def test_the_weekly_job_window_is_refused(world):
    monday = dt.datetime(2030, 1, 7, 5, 30)
    transport = mt.Transport(world["raw"], http=Net({}).http)
    with pytest.raises(fid.FetchError, match="weekly job window"):
        fid.fetch_source(world["inv"], NOV, world["raw"], transport=transport, clock=lambda: monday)


def test_a_second_concurrent_run_is_refused(world):
    with fid.run_lock(world["raw"]):
        with pytest.raises(fid.FetchError, match="another fetch"):
            with fid.run_lock(world["raw"]):
                pass


def test_slug_and_date_row_ids_land_under_their_meeting_id(world):
    run(world, Net({"https://www.townofrossca.gov/robots.txt": (404, b"", {}),
                    "https://www.townofrossca.gov/sites/default/files/fileattachments/town_council/meeting/9/d.pdf":
                        (200, PDF, {})}), ROSS)
    assert (world["raw"] / ROSS / "minutes" / f"meeting-{ROSS}-2030-01-10-row-3.pdf").exists()
