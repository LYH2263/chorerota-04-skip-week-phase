"""Round-robin 相位账本：整周跳过时相位仍按该周应有格数前进。

约定（与生成入口、跳过状态机共同遵守）：
- 每周首次生成或跳过时，把 phase_start（起始相位）与 slot_count（格数）记到 weeks 行上；
- 未记录过的周，其相位 = 此前（按 id 排序）所有已记录周的 slot_count 之和；
- phase_start 一旦记录不再改写——取消跳过、重新生成一律从记录相位起算；
- slot_count 在每次生成/跳过时按当前应有格数刷新，供后续周累加承接。
"""


def ledger_phase(week_rows, week_id: int) -> int:
    """week_id 的记录相位：排在该周之前、已记录 slot_count 的周之格数总和。

    week_rows 须按 id 升序；draft 周（slot_count 为 None）不计入。
    """
    total = 0
    for w in week_rows:
        if w["id"] == week_id:
            break
        total += w["slot_count"] or 0
    return total


def would_be_slots(task_count: int, days: int = 7) -> int:
    """该周应有格数 = 天数 × 任务数；跳过周不生成格子，也按此数推进相位。"""
    return max(task_count, 0) * days
