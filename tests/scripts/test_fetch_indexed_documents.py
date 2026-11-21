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

    def http(self, url, headers, on_head, deadline=None):
        self.deadlines = getattr(self, "deadlines", []) + [deadline]
        self.calls.append((self.t, url))
        self.t += 0.1
        r = self.responses.get(url, (404, b"gone", {}))
        if isinstance(r, Exception):
            raise r
        on_head(r[0], r[2])
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
    fid.freeze_baseline(inv, raw)
    return {"raw": raw, "staging": staging, "sub": sub, "inv": inv}


def run(world, net, source, mode="bulk", **kw):
    transport = mt.Transport(world["raw"], http=net.http, sleep=net.sleep, now=net.now)
    kw.setdefault("require_probe", False)
    return fid.fetch_source(world["inv"], source, world["raw"], mode=mode, transport=transport,
                            clock=lambda: SATURDAY, **kw)


def ledger(world, source, journal=False):
    """The ledger's outcome lines (with journal=True, also the `attempting` lines written before each request)."""
    rows = fid.read_ledger(world["raw"], source)
    return rows if journal else [r for r in rows if r["state"] not in ("attempting", "abandoned")]


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


def test_the_inventory_is_never_overwritten(world):
    before = world["inv"].read_bytes()
    with pytest.raises(fid.FetchError, match="frozen"):
        fid.freeze_inventory(world["sub"], world["raw"], world["staging"])
    assert world["inv"].read_bytes() == before


def test_a_raw_root_other_than_the_inventorys_is_refused(world, tmp_path):
    with pytest.raises(fid.FetchError, match="raw"):
        run({**world, "raw": tmp_path / "elsewhere"}, Net({}), NOV)


def test_live_runs_only_from_the_canonical_raw_root(world):
    with pytest.raises(fid.FetchError, match="canonical"):
        fid.fetch_source(world["inv"], NOV, world["raw"], clock=lambda: SATURDAY)  # no injected transport


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
    again = Net({nov_url(2): (200, PDF, {})})
    assert run(world, again, NOV, mode="probe").attempted == 0 and again.calls == []  # 3 per source, in all
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
    assert reasons[f"meeting-{NOV}-3"] == ("failed", "response is not a PDF, HTML, DOCX or Word .doc document")
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


def test_bulk_requires_a_probe_first(world):
    net = Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)})
    with pytest.raises(fid.FetchError, match="probe"):
        run(world, net, NOV, require_probe=True)
    assert net.calls == []
    run(world, net, NOV, mode="probe", limit=1)
    assert run(world, net, NOV, require_probe=True).attempted == 3


def test_a_failed_redirect_target_is_never_requested_again_for_another_candidate(tmp_path):
    bad = "https://novato.granicus.com/DocumentViewer.php?file=broken.pdf"
    sub = make_substrate(tmp_path / "s.sqlite", meetings=[
        (f"meeting-{NOV}-8", "2030-01-02", "City Council", nov_url(8)),
        (f"meeting-{NOV}-9", "2030-01-01", "City Council", nov_url(9))])
    raw = tmp_path / "raw"
    w = {"raw": raw, "inv": fid.freeze_inventory(sub, raw, tmp_path / "st")}
    net = Net({nov_url(8): (302, b"", {"location": bad}), nov_url(9): (302, b"", {"location": bad}),
               bad: (500, b"", {})})
    run(w, net, NOV)
    assert net.urls().count(bad) == 1
    rows = {r["meeting_id"]: r for r in ledger(w, NOV)}
    assert rows[f"meeting-{NOV}-9"]["state"] == "failed" and "not retried" in rows[f"meeting-{NOV}-9"]["reason"]


def test_an_attempt_interrupted_by_a_crash_is_failed_and_never_retried(world):
    class Crash(BaseException):
        pass

    def explode(url, headers, on_head, deadline=None):
        raise Crash()

    transport = mt.Transport(world["raw"], http=explode)
    with pytest.raises(Crash):
        fid.fetch_source(world["inv"], NOV, world["raw"], transport=transport, clock=lambda: SATURDAY,
                         require_probe=False, limit=1)
    assert ledger(world, NOV, journal=True)[-1]["state"] == "attempting"  # journaled before the request
    net = Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)})
    run(world, net, NOV)
    assert nov_url(5) not in net.urls()
    last = {r["meeting_id"]: r for r in ledger(world, NOV)}
    assert last[f"meeting-{NOV}-5"]["state"] == "failed" and "interrupted" in last[f"meeting-{NOV}-5"]["reason"]


def test_a_torn_last_ledger_line_is_tolerated_by_the_fetcher_and_the_index(world):
    import minutes_text_index as mti
    run(world, Net({nov_url(5): (200, PDF, {})}), NOV, limit=1)
    path = world["raw"] / NOV / fid.FETCH_LOG
    with path.open("a") as fh:
        fh.write('{"meeting_id": "meeting-novato-city-council-4", "sta')
    assert [r["state"] for r in fid.read_ledger(world["raw"], NOV)][-1] == "fetched"
    saved, _, fetched = mti._saved_dates(world["raw"] / NOV)
    assert f"meeting-{NOV}-5.pdf" in saved and fetched[f"meeting-{NOV}-5.pdf"]
    run(world, Net({nov_url(4): (200, PDF, {})}), NOV, limit=1)  # appends after the torn line, still readable
    assert fid.read_ledger(world["raw"], NOV)[-1]["meeting_id"] == f"meeting-{NOV}-4"
    assert (world["raw"] / NOV / (fid.FETCH_LOG + ".torn")).read_text().startswith('{"meeting_id"')


def test_the_window_mid_chain_ends_the_run_and_a_candidate_with_no_request_is_retried_later(world):
    hop = "https://novato.granicus.com/DocumentViewer.php?file=5.pdf"
    net = Net({nov_url(5): (302, b"", {"location": hop}), hop: (200, PDF, {}), nov_url(4): (200, PDF, {})})
    times = iter([SATURDAY, SATURDAY])  # the start check, the first request's guard; then Monday 05:00
    transport = mt.Transport(world["raw"], http=net.http, sleep=net.sleep, now=net.now)
    res = fid.fetch_source(world["inv"], NOV, world["raw"], transport=transport, require_probe=False,
                           clock=lambda: next(times, dt.datetime(2030, 1, 7, 5, 0)))
    assert hop not in net.urls() and "window" in res.skipped
    last = {r["meeting_id"]: r for r in ledger(world, NOV)}
    assert last[f"meeting-{NOV}-5"]["state"] == "failed"  # one request had gone out: never retried
    assert f"meeting-{NOV}-4" not in last


def test_states_reconcile_ledger_claims_with_files_on_disk(world):
    run(world, Net({nov_url(n): (200, PDF + bytes([n]), {}) for n in (2, 3, 4, 5)}), NOV)
    (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-5.pdf").unlink()
    (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-4.pdf").write_bytes(b"%PDF-1.4 changed")
    states = fid.candidate_states(world["inv"], world["raw"])
    assert sorted(a["meeting_id"] for a in states["anomalies"]) == [f"meeting-{NOV}-4", f"meeting-{NOV}-5"]


def test_a_file_saved_by_hand_since_the_freeze_is_recorded_already_cached(world):
    (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-5.html").write_bytes(HTML)
    net = Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4)})
    run(world, net, NOV)
    assert nov_url(5) not in net.urls()
    assert fid.candidate_states(world["inv"], world["raw"])["states"][f"meeting-{NOV}-5"] == "already-cached"


def test_a_shared_url_copy_refuses_a_source_file_that_changed(tmp_path):
    shared = nov_url(9)
    sub = make_substrate(tmp_path / "s.sqlite", meetings=[
        (f"meeting-{NOV}-8", "2030-01-02", "City Council", shared),
        (f"meeting-{NOV}-9", "2030-01-01", "City Council", shared)])
    raw = tmp_path / "raw"
    w = {"raw": raw, "inv": fid.freeze_inventory(sub, raw, tmp_path / "st")}
    run(w, Net({shared: (200, PDF, {})}), NOV, limit=1)
    (raw / NOV / "minutes" / f"meeting-{NOV}-8.pdf").write_bytes(b"%PDF-1.4 tampered")
    run(w, Net({}), NOV)
    last = {r["meeting_id"]: r for r in ledger(w, NOV)}
    assert last[f"meeting-{NOV}-9"]["state"] == "failed" and "changed" in last[f"meeting-{NOV}-9"]["reason"]
    assert not (raw / NOV / "minutes" / f"meeting-{NOV}-9.pdf").exists()


def test_fetched_slug_and_date_row_documents_are_indexed_end_to_end(world, tmp_path):
    import minutes_text_index as mti
    from test_minutes_text_index import make_pdf
    long = " The invented Ross council approved a gazebo." * 6
    ross = "https://www.townofrossca.gov/sites/default/files/fileattachments/town_council/meeting/9/d.pdf"
    run(world, Net({"https://www.townofrossca.gov/robots.txt": (404, b"", {}),
                    ross: (200, make_pdf(["Ross minutes January 10, 2030." + long]), {})}), ROSS)
    run(world, Net({f"{GCS}/robots.txt": ALLOW_ALL,
                    fx_url("a"): (200, make_pdf(["Fairfax minutes January 3, 2030." + long]), {})}), FX)
    report = mti.build_index(raw=world["raw"], substrate=world["sub"], out=tmp_path / "i.sqlite",
                             sources=(ROSS, FX))
    d = {Path(f["path"]).name: f["disposition"] for f in report["files"]}
    assert d == {f"meeting-{ROSS}-2030-01-10-row-3.pdf": "indexed",
                 f"meeting-{FX}-town-council-meeting-january-3-2030.pdf": "indexed"}


def test_an_interrupted_redirect_hop_is_never_requested_again(tmp_path):
    hop = "https://novato.granicus.com/DocumentViewer.php?file=shared.pdf"
    sub = make_substrate(tmp_path / "s.sqlite", meetings=[
        (f"meeting-{NOV}-8", "2030-01-02", "City Council", nov_url(8)),
        (f"meeting-{NOV}-9", "2030-01-01", "City Council", nov_url(9))])
    raw = tmp_path / "raw"
    w = {"raw": raw, "inv": fid.freeze_inventory(sub, raw, tmp_path / "st")}
    fid.freeze_baseline(w["inv"], raw)

    class Crash(BaseException):
        pass

    net = Net({nov_url(8): (302, b"", {"location": hop}), nov_url(9): (302, b"", {"location": hop}),
               hop: (200, PDF, {})})

    def crash_on_hop(url, headers, on_head, deadline=None):
        if url == hop:
            raise Crash()
        return net.http(url, headers, on_head)

    t = mt.Transport(raw, http=crash_on_hop, sleep=net.sleep, now=net.now)
    with pytest.raises(Crash):
        fid.fetch_source(w["inv"], NOV, raw, transport=t, clock=lambda: SATURDAY, require_probe=False)
    later = Net({nov_url(9): (302, b"", {"location": hop}), hop: (200, PDF, {})}, )
    later.t = net.t + 1000
    run(w, later, NOV)
    assert hop not in later.urls()
    last = {r["meeting_id"]: r for r in ledger(w, NOV)}
    assert last[f"meeting-{NOV}-8"]["state"] == "failed" and hop in last[f"meeting-{NOV}-8"]["interrupted_urls"]
    assert last[f"meeting-{NOV}-9"]["state"] == "failed" and "not retried" in last[f"meeting-{NOV}-9"]["reason"]


def test_probe_slots_are_reserved_before_the_request_and_bulk_needs_a_completed_probe(world):
    class Crash(BaseException):
        pass

    def explode(url, headers, on_head, deadline=None):
        raise Crash()

    t = mt.Transport(world["raw"], http=explode)
    with pytest.raises(Crash):
        fid.fetch_source(world["inv"], NOV, world["raw"], mode="probe", transport=t, clock=lambda: SATURDAY)
    net = Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)})
    with pytest.raises(fid.FetchError, match="probe"):  # an interrupted probe is no completed probe
        run(world, net, NOV, require_probe=True)
    assert run(world, net, NOV, mode="probe").attempted == 2  # 1 slot used by the crashed attempt
    assert run(world, net, NOV, require_probe=True).attempted == 1


def test_the_guard_gives_each_request_a_deadline_at_the_window_and_refuses_near_it(world):
    net = Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)})
    sunday_late = dt.datetime(2030, 1, 6, 23, 0)  # six hours before Monday 05:00
    transport = mt.Transport(world["raw"], http=net.http, sleep=net.sleep, now=net.now)
    fid.fetch_source(world["inv"], NOV, world["raw"], transport=transport, require_probe=False, limit=1,
                     clock=lambda: sunday_late)
    assert net.deadlines[0] == pytest.approx(net.calls[0][0] + mt.MAX_TRANSFER_S)  # six hours off: the cap
    close = dt.datetime(2030, 1, 7, 4, 49)  # 11 minutes before: the window sets the deadline
    fid.fetch_source(world["inv"], NOV, world["raw"], transport=transport, require_probe=False, limit=1,
                     clock=lambda: close)
    assert net.deadlines[1] == pytest.approx(net.calls[1][0] + 660 - mt.READ_TIMEOUT_S - mt.DEADLINE_MARGIN_S)
    almost = dt.datetime(2030, 1, 7, 4, 58)
    res = fid.fetch_source(world["inv"], NOV, world["raw"], transport=transport, require_probe=False,
                           clock=lambda: almost)
    assert "window" in res.skipped and len(net.calls) == 2


def test_a_frozen_cached_file_that_disappears_or_changes_is_an_anomaly(world):
    (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-1.pdf").write_bytes(b"%PDF-1.4 edited later")
    states = fid.candidate_states(world["inv"], world["raw"])
    assert [a["meeting_id"] for a in states["anomalies"]] == [f"meeting-{NOV}-1"]
    with pytest.raises(fid.FetchError, match="frozen"):
        fid.freeze_baseline(world["inv"], world["raw"])


def test_states_refuse_without_a_baseline(tmp_path):
    sub = make_substrate(tmp_path / "s.sqlite")
    inv = fid.freeze_inventory(sub, tmp_path / "raw", tmp_path / "st")
    with pytest.raises(fid.FetchError, match="baseline"):
        fid.candidate_states(inv, tmp_path / "raw")


def test_a_hand_saved_file_is_recorded_so_the_index_can_date_it(world):
    import minutes_text_index as mti
    (world["raw"] / NOV / "minutes" / f"meeting-{NOV}-5.html").write_bytes(HTML)
    run(world, Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4)}), NOV)
    saved, _, fetched = mti._saved_dates(world["raw"] / NOV)
    assert f"meeting-{NOV}-5.html" in saved and fetched[f"meeting-{NOV}-5.html"] == {fid.sha256_bytes(HTML)}


def test_a_limit_truncated_run_reports_its_remainder(world):
    res = run(world, Net({nov_url(n): (200, PDF, {}) for n in (2, 3, 4, 5)}), NOV, limit=1)
    assert res.attempted == 1 and res.remaining == 3


def test_the_inventory_is_published_whole_or_not_at_all(tmp_path, monkeypatch):
    sub = make_substrate(tmp_path / "s.sqlite")
    real = fid.os.link
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if str(dst).endswith(".sha256"):
            raise OSError("crash between the two files")
        return real(src, dst)

    monkeypatch.setattr(fid.os, "link", flaky)
    with pytest.raises(OSError):
        fid.freeze_inventory(sub, tmp_path / "raw", tmp_path / "st")
    with pytest.raises(fid.FetchError, match="sha256"):
        fid.load_inventory(tmp_path / "st" / fid.INVENTORY)  # an incomplete freeze is detected, never trusted


def test_two_competing_processes_never_both_hold_the_lock(world):
    import subprocess
    code = ("import sys, time; sys.path.insert(0, %r); import fetch_indexed_documents as f\n"
            "with f.run_lock(%r):\n    print('held', flush=True); time.sleep(3)\n")
    scripts = str(Path(fid.__file__).parent)
    p = subprocess.Popen([sys.executable, "-c", code % (scripts, str(world["raw"]))], stdout=subprocess.PIPE,
                         text=True)
    assert p.stdout.readline().strip() == "held"
    try:
        with pytest.raises(fid.FetchError, match="another fetch"):
            with fid.run_lock(world["raw"]):
                pass
    finally:
        p.wait()


def test_a_window_interruption_keeps_the_requested_hops_and_is_no_completed_probe(world):
    hop = "https://novato.granicus.com/DocumentViewer.php?file=5.pdf"
    net = Net({nov_url(5): (302, b"", {"location": hop}), hop: (200, PDF, {})})
    times = iter([SATURDAY, SATURDAY])
    transport = mt.Transport(world["raw"], http=net.http, sleep=net.sleep, now=net.now)
    fid.fetch_source(world["inv"], NOV, world["raw"], mode="probe", transport=transport,
                     clock=lambda: next(times, dt.datetime(2030, 1, 7, 5, 0)))
    last = {r["meeting_id"]: r for r in ledger(world, NOV)}[f"meeting-{NOV}-5"]
    assert last["state"] == "failed" and last["interrupted_urls"] == [nov_url(5)]
    with pytest.raises(fid.FetchError, match="probe"):
        run(world, Net({}), NOV, require_probe=True)


# --- probe-driven changes (Phase C, 2026-11-21) ------------------------------------------------------------------

TB, MV, SZ = "tiburon-town-council-granicus", "mill-valley-committees", "sausalito-city-council"
def make_ole2(stream_name="WordDocument", sector_shift=9, truncate=None, stream_size=4096, fib=b"\xec\xa5",
              chain=None, stream_bytes=None, root_child=1, zero_root=False):
    """A minimal valid compound file: header; sector 0 the FAT, sector 1 the directory (a root entry and one
    stream entry), sectors 2.. the stream. `chain` overrides the stream's FAT entries; `stream_bytes` the bytes
    actually present."""
    import struct
    size = 1 << sector_shift
    n = max(1, -(-stream_size // size))
    header = bytearray(512)
    header[0:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHH", header, 24, 0x3E, 3 if sector_shift == 9 else 4, 0xFFFE, sector_shift)
    struct.pack_into("<I", header, 44, 1)        # one FAT sector
    struct.pack_into("<I", header, 48, 1)        # the directory starts at sector 1
    struct.pack_into("<I", header, 60, 0xFFFFFFFE)  # no mini FAT
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)  # no extra DIFAT
    header[76:512] = b"\xff" * 436
    struct.pack_into("<I", header, 76, 0)        # DIFAT[0]: the FAT is sector 0
    fat = [0xFFFFFFFD, 0xFFFFFFFE] + (chain if chain is not None else [3 + i for i in range(n - 1)] + [0xFFFFFFFE])
    fat_sector = bytearray(b"\xff" * size)
    for i, v in enumerate(fat[: size // 4]):
        struct.pack_into("<I", fat_sector, i * 4, v)
    directory = bytearray(size)
    for i, (name, kind) in enumerate((("Root Entry", 5), (stream_name, 2))):
        raw = name.encode("utf-16-le") + b"\0\0"
        directory[i * 128:i * 128 + len(raw)] = raw
        struct.pack_into("<HB", directory, i * 128 + 64, len(raw), kind)
        struct.pack_into("<III", directory, i * 128 + 68, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)  # no siblings/child
        if kind == 5:
            struct.pack_into("<I", directory, i * 128 + 76, root_child)
        if kind == 2:
            struct.pack_into("<IQ", directory, i * 128 + 116, 2, stream_size)
    if zero_root:
        directory[0:128] = bytes(128)
    stream = stream_bytes if stream_bytes is not None else fib + b"\0" * (n * size - len(fib))
    pad = b"\0" * (size - 512) if size > 512 else b""
    data = bytes(header) + pad + bytes(fat_sector) + bytes(directory) + stream
    return data[:truncate] if truncate else data


OLE2 = make_ole2()


def _overlapping_directory():
    import struct
    data = bytearray(make_ole2())
    struct.pack_into("<I", data, 512 + 4, 2)  # FAT[1] (the directory) now continues into sector 2, the stream
    return bytes(data)


def _one(tmp_path, mid, url, date="2030-01-05", title="Town Council Regular Meeting"):
    sub = make_substrate(tmp_path / "s.sqlite", meetings=[(mid, date, title, url)])
    raw = tmp_path / "raw"
    w = {"raw": raw, "inv": fid.freeze_inventory(sub, raw, tmp_path / "st")}
    fid.freeze_baseline(w["inv"], raw)
    return w


def test_a_legacy_word_doc_is_filed_as_doc(tmp_path):
    url = "https://sausalito.granicus.com/MinutesViewer.php?view_id=6&clip_id=1"
    w = _one(tmp_path, f"meeting-{SZ}-1", url, title="City Council")
    run(w, Net({url: (200, OLE2, {})}), SZ)
    assert (w["raw"] / SZ / "minutes" / f"meeting-{SZ}-1.doc").read_bytes() == OLE2
    assert ledger(w, SZ)[0]["state"] == "fetched"


def test_a_google_viewer_wrapper_is_unwrapped_to_the_sources_own_document_and_never_requested(tmp_path):
    url = "https://townoftiburon.granicus.com/MinutesViewer.php?view_id=5&clip_id=1439&doc_id=x"
    inner = "https://townoftiburon.granicus.com/DocumentViewer.php?file=townoftiburon_cb52.pdf&view=1"
    gview = ("https://docs.google.com/gview?url=https%3A%2F%2Ftownoftiburon.granicus.com%2FDocumentViewer.php"
             "%3Ffile%3Dtownoftiburon_cb52.pdf%26view%3D1&embedded=true")
    w = _one(tmp_path, f"meeting-{TB}-1439", url)
    net = Net({url: (302, b"", {"location": gview}), inner: (200, PDF, {})})
    run(w, net, TB)
    assert net.urls() == [url, inner] and not any("google" in u for u in net.urls())
    row = ledger(w, TB)[0]
    assert row["state"] == "fetched" and row["chain"][0]["unwrapped"] == inner


@pytest.mark.parametrize("inner", [
    "https://evil.example/x.pdf",                                        # not the source's host
    "https://townoftiburon.granicus.com/../x.pdf",                         # not canonical
    "https://www.novato.gov/x.pdf",                                        # off-limits
])
def test_a_viewer_wrapping_anything_else_is_logged_and_not_requested(tmp_path, inner):
    from urllib.parse import quote
    url = "https://townoftiburon.granicus.com/MinutesViewer.php?view_id=5&clip_id=1"
    gview = f"https://docs.google.com/gview?url={quote(inner, safe='')}&embedded=true"
    w = _one(tmp_path, f"meeting-{TB}-1", url)
    net = Net({url: (302, b"", {"location": gview}), inner: (200, PDF, {})})
    run(w, net, TB)
    assert net.urls() == [url] and ledger(w, TB)[0]["state"] == "failed"


def test_a_viewer_on_a_source_without_the_unwrap_rule_is_not_unwrapped(tmp_path):
    from urllib.parse import quote
    url = "https://novato.granicus.com/MinutesViewer.php?clip_id=3"
    inner = "https://novato.granicus.com/DocumentViewer.php?file=n.pdf&view=1"
    gview = f"https://docs.google.com/gview?url={quote(inner, safe='')}&embedded=true"
    w = _one(tmp_path, f"meeting-{NOV}-3", url, title="City Council")
    net = Net({url: (302, b"", {"location": gview}), inner: (200, PDF, {})})
    run(w, net, NOV)
    assert net.urls() == [url]


def test_mill_valley_org_documents_reach_the_gov_host_with_https_upgrade_only_when_admitted(tmp_path):
    url = "https://cityofmillvalley.org/AgendaCenter/ViewFile/Minutes/_04082021-10"
    gov = "https://www.cityofmillvalley.gov/AgendaCenter/ViewFile/Minutes/_04082021-10"
    w = _one(tmp_path, f"meeting-{MV}-10", url, title="Arts Commission Regular Meeting Agenda (PDF)")
    net = Net({"https://cityofmillvalley.org/robots.txt":
               (301, b"", {"location": "http://www.cityofmillvalley.gov/robots.txt"}),
               "https://www.cityofmillvalley.gov/robots.txt": ALLOW_ALL,
               url: (301, b"", {"location": "http://www.cityofmillvalley.gov/AgendaCenter/ViewFile/Minutes/_04082021-10"}),
               gov: (200, PDF, {})})
    run(w, net, MV)
    assert net.urls() == ["https://cityofmillvalley.org/robots.txt", "https://www.cityofmillvalley.gov/robots.txt",
                          url, gov]
    assert ledger(w, MV)[0]["state"] == "fetched"
    assert not any(u.startswith("http://") for u in net.urls())


def test_an_http_redirect_is_upgraded_only_to_an_admitted_https_url(tmp_path):
    url = "https://cityofmillvalley.org/AgendaCenter/ViewFile/Minutes/_1-11"
    w = _one(tmp_path, f"meeting-{MV}-11", url, title="Arts Commission Regular Meeting Agenda (PDF)")
    net = Net({"https://cityofmillvalley.org/robots.txt": ALLOW_ALL,
               url: (301, b"", {"location": "http://www.cityofmillvalley.gov/Archive/elsewhere.pdf"})})
    run(w, net, MV)
    assert len(net.urls()) == 2 and ledger(w, MV)[0]["state"] == "failed"


def test_an_attempt_excluded_before_any_document_request_uses_no_probe_slot(world):
    net = Net({"https://www.townofrossca.gov/robots.txt": OSError("dropped")})
    run(world, net, ROSS, mode="probe")
    assert ledger(world, ROSS)[0]["state"] == "excluded-by-authorization"
    rows = fid.read_ledger(world["raw"], ROSS)
    assert not fid.probe_completed(rows)  # no document was requested: bulk would still refuse
    assert fid.probe_slots_used(rows) == 0  # and a later probe keeps its slots (this candidate is terminal)


@pytest.mark.parametrize("data", [
    bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 512,   # the signature and nothing behind it
    make_ole2(truncate=700),                            # cut off inside the directory sector
    make_ole2(stream_name="Workbook"),                  # an Excel file, not Word
    make_ole2(stream_name="PowerPoint Document"),
    make_ole2(stream_size=10_000_000),                  # a stream longer than the file
    make_ole2(fib=b"\x00\x00"),                         # no Word FIB at the stream's start
    make_ole2(sector_shift=12, stream_bytes=b"\xec\xa5"),  # declares 4096 bytes, holds two
    make_ole2(chain=[2]),                               # the chain loops on itself
    make_ole2(chain=[3, 4, 0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFE]),  # too short
    make_ole2(zero_root=True),                          # no root entry
    make_ole2(root_child=0xFFFFFFFF),                   # the stream is not reachable from the root
    _overlapping_directory(),                            # the directory chain claims the stream's sectors
], ids=["signature-only", "truncated", "excel", "powerpoint", "stream-too-long", "no-fib", "fib-only",
        "chain-loop", "chain-short", "no-root", "unreachable", "overlap"])
def test_only_a_structurally_valid_word_file_is_a_doc(data):
    assert fid._document_kind(data) is None


def test_a_version_4_word_file_is_a_doc():
    assert fid._document_kind(make_ole2(sector_shift=12)) == "doc"


def test_the_five_real_san_anselmo_word_files_are_docs():
    raw = Path("~/projects/marin-civic-graph/data/raw/san-anselmo-town-council/minutes").expanduser()
    files = [raw / f"meeting-san-anselmo-town-council-{n}.html" for n in (2077, 2591, 2592, 929, 940)]
    if not all(f.is_file() for f in files):
        pytest.skip("the canonical raw store is not on this machine")
    assert [fid._document_kind(f.read_bytes()) for f in files] == ["doc"] * 5


def test_exclude_gives_the_remaining_candidates_a_terminal_state_without_a_request(world):
    net = Net({})
    t = mt.Transport(world["raw"], http=net.http, sleep=net.sleep, now=net.now)
    res = fid.exclude_remaining(world["inv"], NOV, world["raw"], "robots.txt unreadable twice", transport=t)
    assert net.calls == [] and len(res) == 4
    assert {r["state"] for r in ledger(world, NOV)} == {"excluded-by-authorization"}
    assert fid.candidate_states(world["inv"], world["raw"])["counts"][NOV] == {
        "already-cached": 1, "excluded-by-authorization": 4}
