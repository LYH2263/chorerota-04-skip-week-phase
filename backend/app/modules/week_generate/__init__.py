"""Week generation entry point.

Builds a week's assignments from the round-robin stream at the week's
recorded start phase. Skipped weeks never enter here: their cells are
accounted for by the phase accumulator, so regenerating a week that sits
after (or before) a skipped one lands on the same member the skipped cells
would have consumed.
"""

from app.engines.rota import build_week_slots
from app.modules.skip_week import SkipError, week_row, record_phase

DEFAULT_DAYS = 7


def generate_week(c, week_id: int, days: int = DEFAULT_DAYS) -> dict:
    """(Re)generate assignments for a week; rejected while status='skipped'."""
    week = week_row(c, week_id)
    if week["status"] == "skipped":
        raise SkipError("week_skipped")
    mids = [r["id"] for r in c.execute(
        "SELECT id FROM members WHERE active=1 AND data_quality='clean' ORDER BY id")]
    tids = [r["id"] for r in c.execute(
        "SELECT id FROM tasks WHERE data_quality='clean' AND weight>0 ORDER BY id")]
    phase = record_phase(c, week_id, days)
    slots = build_week_slots(mids, tids, days=days, offset=phase)
    c.execute("DELETE FROM assignments WHERE week_id=?", (week_id,))
    for s in slots:
        c.execute(
            "INSERT INTO assignments(week_id,day,task_id,member_id) VALUES (?,?,?,?)",
            (week_id, s["day"], s["task_id"], s["member_id"]))
    c.execute("UPDATE weeks SET status='ready' WHERE id=?", (week_id,))
    c.commit()
    return {"count": len(slots), "slots": slots, "phase_start": phase}
