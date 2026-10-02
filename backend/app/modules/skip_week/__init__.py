"""Skip-week state machine.

Decision (fixed for frontend and backend): marking a week that already has
assignments as skipped FORCES the cleanup — every assignment of that week is
deleted and its pending swap requests are voided. There is no reject-and-keep
alternative; the UI asks for confirmation before calling the endpoint.

A skipped week produces no assignments but keeps its recorded round-robin
phase (``phase_start``) and intended grid size (``grid_size``), so later
weeks continue exactly where they would have. Un-skipping restores the week
to an empty ``draft``; regenerating it replays from the recorded phase.
"""

from app.engines.phase import recorded_phase

DEFAULT_DAYS = 7


class SkipError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def week_row(c, week_id: int) -> dict:
    row = c.execute("SELECT * FROM weeks WHERE id=?", (week_id,)).fetchone()
    if row is None:
        raise SkipError("week_not_found")
    return dict(row)


def eligible_task_count(c) -> int:
    return c.execute(
        "SELECT COUNT(*) FROM tasks WHERE data_quality='clean' AND weight>0"
    ).fetchone()[0]


def preceding_grid_sizes(c, week_id: int) -> list[int]:
    """Cells consumed by earlier weeks.

    Preference order per earlier week: recorded ``grid_size``; otherwise the
    number of its existing assignments; otherwise 0 (an untouched draft).
    """
    rows = c.execute(
        """
        SELECT COALESCE(w.grid_size,
                        (SELECT COUNT(*) FROM assignments a WHERE a.week_id = w.id)) AS size
          FROM weeks w
         WHERE w.id < ?
         ORDER BY w.id
        """,
        (week_id,),
    ).fetchall()
    return [r["size"] for r in rows]


def resolve_phase_start(c, week: dict, week_id: int) -> int:
    """Recorded start phase if known, else the sum over preceding weeks."""
    if week.get("phase_start") is not None:
        return int(week["phase_start"])
    return recorded_phase(preceding_grid_sizes(c, week_id))


def record_phase(c, week_id: int, days: int = DEFAULT_DAYS) -> int:
    """Persist grid_size (from current eligible tasks) and phase_start."""
    week = week_row(c, week_id)
    if week.get("grid_size") is None:
        week["grid_size"] = days * eligible_task_count(c)
        c.execute("UPDATE weeks SET grid_size=? WHERE id=?", (week["grid_size"], week_id))
    phase = resolve_phase_start(c, week, week_id)
    c.execute("UPDATE weeks SET phase_start=? WHERE id=?", (phase, week_id))
    return phase


def mark_skipped(c, week_id: int, days: int = DEFAULT_DAYS) -> dict:
    """draft/ready -> skipped.

    Forced-cleanup policy: assignments are deleted and pending swaps voided,
    even for a week that was already generated.
    """
    week = week_row(c, week_id)
    if week["status"] == "skipped":
        raise SkipError("already_skipped")
    phase = record_phase(c, week_id, days)
    grid_size = c.execute("SELECT grid_size FROM weeks WHERE id=?", (week_id,)).fetchone()["grid_size"]
    deleted = c.execute("DELETE FROM assignments WHERE week_id=?", (week_id,)).rowcount
    voided = c.execute(
        "UPDATE swap_requests SET status='void' WHERE week_id=? AND status='pending'",
        (week_id,),
    ).rowcount
    c.execute("UPDATE weeks SET status='skipped' WHERE id=?", (week_id,))
    c.commit()
    return {
        "week_id": week_id,
        "status": "skipped",
        "phase_start": phase,
        "grid_size": grid_size,
        "assignments_deleted": deleted,
        "swaps_voided": voided,
    }


def unskip(c, week_id: int) -> dict:
    """skipped -> draft (empty). Recorded phase/grid are retained on purpose."""
    week = week_row(c, week_id)
    if week["status"] != "skipped":
        raise SkipError("not_skipped")
    c.execute("UPDATE weeks SET status='draft' WHERE id=?", (week_id,))
    c.commit()
    return {"week_id": week_id, "status": "draft"}
