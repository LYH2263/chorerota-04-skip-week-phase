"""整周跳过状态机（相位累加见 app.engines.phase，生成入口见 app.main）。

状态机：
    draft --generate--> ready
    draft / ready --skip--> skipped
    skipped --unskip--> draft        （保留记录相位，重新生成时从该相位起算）
其余迁移一律非法。

带格周取舍（前后端一致，拍板）：对已落格的周标记跳过时，**清空该周
assignments 并作废其 pending 对调**（status='void'），而不是拒绝并保持原状——
拒绝会让已生成的周没有任何路径进入跳过态。整个迁移在同一事务里完成。
"""

from app.engines.phase import ledger_phase, would_be_slots

LEGAL_TRANSITIONS = {
    ("draft", "skipped"),
    ("ready", "skipped"),
    ("skipped", "draft"),
}


class IllegalTransition(Exception):
    """当前状态不允许的目标迁移。"""

    def __init__(self, current: str, target: str):
        self.current, self.target = current, target
        super().__init__(f"illegal_transition:{current}->{target}")


def check_transition(current: str, target: str) -> None:
    if (current, target) not in LEGAL_TRANSITIONS:
        raise IllegalTransition(current, target)


def _get_week(conn, week_id: int):
    week = conn.execute("SELECT * FROM weeks WHERE id=?", (week_id,)).fetchone()
    if week is None:
        raise KeyError(week_id)
    return week


def _recorded_or_ledger_phase(conn, week) -> int:
    """已记录相位优先；未记录过则按账本累加（此时落账，之后不再改写）。"""
    if week["phase_start"] is not None:
        return week["phase_start"]
    rows = conn.execute("SELECT id, slot_count FROM weeks ORDER BY id").fetchall()
    return ledger_phase(rows, week["id"])


def _clean_task_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM tasks WHERE data_quality='clean' AND weight>0"
    ).fetchone()["c"]


def skip_week(conn, week_id: int, days: int = 7) -> dict:
    """draft/ready -> skipped：清空格子、作废 pending 对调、按应有格数落账相位。"""
    week = _get_week(conn, week_id)
    check_transition(week["status"], "skipped")
    phase = _recorded_or_ledger_phase(conn, week)
    slots = would_be_slots(_clean_task_count(conn), days)
    conn.execute("DELETE FROM assignments WHERE week_id=?", (week_id,))
    conn.execute(
        "UPDATE swap_requests SET status='void' WHERE week_id=? AND status='pending'",
        (week_id,),
    )
    conn.execute(
        "UPDATE weeks SET status='skipped', phase_start=?, slot_count=? WHERE id=?",
        (phase, slots, week_id),
    )
    return {"id": week_id, "status": "skipped", "phase_start": phase, "slot_count": slots}


def unskip_week(conn, week_id: int) -> dict:
    """skipped -> draft：不生成格子；phase_start/slot_count 保留，供重新生成起算。"""
    week = _get_week(conn, week_id)
    check_transition(week["status"], "draft")
    conn.execute("UPDATE weeks SET status='draft' WHERE id=?", (week_id,))
    return {
        "id": week_id,
        "status": "draft",
        "phase_start": week["phase_start"],
        "slot_count": week["slot_count"],
    }
