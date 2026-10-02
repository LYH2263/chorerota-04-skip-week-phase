import os
import pytest

from app.db import connect
from app.seed import init_db
from app.engines.rota import build_week_slots
from app.engines.phase import recorded_phase
from app.modules.skip_week import SkipError, mark_skipped, unskip
from app.modules.week_generate import generate_week


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    init_db()
    conn = connect()
    yield conn
    conn.close()


def add_week(conn, label):
    return conn.execute(
        "INSERT INTO weeks(label,status) VALUES (?,?)", (label, "draft")
    ).lastrowid


def clean_member_ids(conn):
    return [r["id"] for r in conn.execute(
        "SELECT id FROM members WHERE active=1 AND data_quality='clean' ORDER BY id")]


def clean_task_ids(conn):
    return [r["id"] for r in conn.execute(
        "SELECT id FROM tasks WHERE data_quality='clean' AND weight>0 ORDER BY id")]


def assignment_count(conn, week_id):
    return conn.execute(
        "SELECT COUNT(*) n FROM assignments WHERE week_id=?", (week_id,)
    ).fetchone()["n"]


# --- engine primitives -----------------------------------------------------

def test_recorded_phase_sums_preceding_grids():
    assert recorded_phase([21, None, 21]) == 42


def test_build_slots_offset_advances_phase():
    stream = build_week_slots([1, 2, 3], [10], days=8)           # 8 cells
    shifted = build_week_slots([1, 2, 3], [10], days=4, offset=4)
    # the offset week must be a window into the same endless round-robin
    assert [s["member_id"] for s in shifted] == \
           [s["member_id"] for s in stream[4:8]]
    assert shifted[0]["member_id"] == 2                          # 4 % 3 == 1


# --- 1. skip an empty week --------------------------------------------------

def test_skip_empty_week_keeps_empty_table_and_records_phase(c):
    wid = add_week(c, "第13周")
    result = mark_skipped(c, wid)

    assert result["status"] == "skipped"
    assert result["assignments_deleted"] == 0
    assert assignment_count(c, wid) == 0
    row = c.execute("SELECT * FROM weeks WHERE id=?", (wid,)).fetchone()
    assert row["status"] == "skipped"
    # 3 eligible tasks * 7 days of cells the round-robin must still walk over
    assert row["grid_size"] == 21
    assert row["phase_start"] == 0


def test_cannot_skip_twice_or_unskip_draft(c):
    wid = add_week(c, "第13周")
    mark_skipped(c, wid)
    with pytest.raises(SkipError) as e:
        mark_skipped(c, wid)
    assert e.value.reason == "already_skipped"

    other = add_week(c, "第14周")
    with pytest.raises(SkipError) as e:
        unskip(c, other)
    assert e.value.reason == "not_skipped"


# --- 2. phase continuity across a skipped week ------------------------------

def test_skipped_week_advances_phase_for_later_weeks(c):
    # a 4th member makes 21 cells non-aligned with the roster (21 % 4 == 1)
    cur = c.execute("INSERT INTO members(name,active,data_quality) VALUES ('小四',1,'clean')")
    fourth = cur.lastrowid
    mids, tids = clean_member_ids(c), clean_task_ids(c)
    assert len(mids) == 4 and len(tids) == 3

    w1 = add_week(c, "第13周")
    w2 = add_week(c, "第14周")
    w3 = add_week(c, "第15周")

    r1 = generate_week(c, w1)
    assert r1["phase_start"] == 0
    r2 = mark_skipped(c, w2)
    assert r2["phase_start"] == 21 and r2["grid_size"] == 21
    assert assignment_count(c, w2) == 0
    r3 = generate_week(c, w3)

    # week 3 starts at 42 cells consumed, exactly as if week 2 had been built
    assert r3["phase_start"] == 42
    expected = build_week_slots(mids, tids, days=7, offset=42)
    got = [dict(r) for r in c.execute(
        "SELECT day,task_id,member_id FROM assignments WHERE week_id=? ORDER BY day,task_id", (w3,))]
    assert [(s["day"], s["task_id"], s["member_id"]) for s in expected] == \
           [(g["day"], g["task_id"], g["member_id"]) for g in got]
    # the skipped 21 cells shifted the first slot: 42 % 4 == 2
    assert got[0]["member_id"] == mids[42 % len(mids)]
    assert fourth in mids


def test_skipped_week_matches_normal_generation_for_followups(c):
    """A skipped week and a generated week must leave later weeks identical."""
    def build_world():
        w1, w2, w3 = add_week(c, "a"), add_week(c, "b"), add_week(c, "c")
        return w1, w2, w3

    # world A: generate every week
    a1, a2, a3 = build_world()
    generate_week(c, a1); generate_week(c, a2); generate_week(c, a3)
    rows_a = [r["member_id"] for r in c.execute(
        "SELECT member_id FROM assignments WHERE week_id=? ORDER BY day,task_id", (a3,))]

    # world B: skip the middle week
    b1, b2, b3 = build_world()
    generate_week(c, b1); mark_skipped(c, b2); generate_week(c, b3)
    rows_b = [r["member_id"] for r in c.execute(
        "SELECT member_id FROM assignments WHERE week_id=? ORDER BY day,task_id", (b3,))]

    assert rows_a == rows_b


# --- 3. un-skip replays from the recorded phase -----------------------------

def test_unskip_then_regenerate_replays_from_recorded_phase(c):
    cur = c.execute("INSERT INTO members(name,active,data_quality) VALUES ('小四',1,'clean')")
    mids, tids = clean_member_ids(c), clean_task_ids(c)

    w1, w2 = add_week(c, "第13周"), add_week(c, "第14周")
    generate_week(c, w1)
    mark_skipped(c, w2)

    unskip(c, w2)
    assert c.execute("SELECT status FROM weeks WHERE id=?", (w2,)).fetchone()["status"] == "draft"
    # phase fields are retained, not reset
    row = c.execute("SELECT phase_start,grid_size FROM weeks WHERE id=?", (w2,)).fetchone()
    assert row["phase_start"] == 21 and row["grid_size"] == 21

    result = generate_week(c, w2)
    expected = build_week_slots(mids, tids, days=7, offset=21)
    got = [dict(r) for r in c.execute(
        "SELECT day,task_id,member_id FROM assignments WHERE week_id=? ORDER BY day,task_id", (w2,))]
    assert result["phase_start"] == 21
    assert [(s["day"], s["task_id"], s["member_id"]) for s in expected] == \
           [(g["day"], g["task_id"], g["member_id"]) for g in got]
    # 21 % 4 == 1: regeneration does not restart the roster from zero
    assert got[0]["member_id"] == mids[1]


def test_generate_rejected_while_skipped(c):
    wid = add_week(c, "第13周")
    mark_skipped(c, wid)
    with pytest.raises(SkipError) as e:
        generate_week(c, wid)
    assert e.value.reason == "week_skipped"
    assert assignment_count(c, wid) == 0


# --- 4. skipping a populated week: forced cleanup decision ------------------

def test_skip_generated_week_clears_cells_and_voids_pending_swaps(c):
    wid = add_week(c, "第13周")
    generate_week(c, wid)
    assert assignment_count(c, wid) == 21
    # two pending swaps + one already confirmed, which must survive untouched
    c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note)"
        " VALUES (?,?,?,?,?,?,?)", (wid, 0, 1, 1, 1, "pending", ""))
    c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note)"
        " VALUES (?,?,?,?,?,?,?)", (wid, 0, 2, 2, 2, "pending", ""))
    c.execute(
        "INSERT INTO swap_requests(week_id,a_day,a_task,b_day,b_task,status,note)"
        " VALUES (?,?,?,?,?,?,?)", (wid, 1, 3, 3, 3, "confirmed", ""))
    c.commit()

    result = mark_skipped(c, wid)
    assert result["assignments_deleted"] == 21
    assert result["swaps_voided"] == 2
    assert assignment_count(c, wid) == 0
    statuses = [r["status"] for r in c.execute(
        "SELECT status FROM swap_requests WHERE week_id=? ORDER BY id", (wid,))]
    assert statuses == ["void", "void", "confirmed"]


# --- 5. household rename is orthogonal to skip state ------------------------

def test_renaming_household_does_not_touch_skip_marks(c):
    wid = add_week(c, "第13周")
    mark_skipped(c, wid)
    before = dict(c.execute("SELECT * FROM weeks WHERE id=?", (wid,)).fetchone())

    c.execute(
        "INSERT INTO settings(key,value) VALUES ('household',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("红纸之家",))
    c.commit()

    after = dict(c.execute("SELECT * FROM weeks WHERE id=?", (wid,)).fetchone())
    assert after["status"] == "skipped"
    assert after["phase_start"] == before["phase_start"]
    assert after["grid_size"] == before["grid_size"]
    assert assignment_count(c, wid) == 0
