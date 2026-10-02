"""整周跳过：状态机、相位累加、带格周取舍、设置隔离。

直接调用 main 里的生成/跳过入口函数（FastAPI 端点即普通函数），
DATA_DIR 指向 tmp_path，每例独立建库。
"""
import pytest
from fastapi import HTTPException

from app import main, seed
from app.db import connect
from app.engines.phase import ledger_phase, would_be_slots
from app.engines.rota import build_week_slots
from app.modules import skip_week as sk


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()


def _week(wid):
    c = connect(); w = dict(c.execute("SELECT * FROM weeks WHERE id=?", (wid,)).fetchone()); c.close(); return w


def _assigns(wid):
    c = connect()
    rows = [dict(r) for r in c.execute("SELECT * FROM assignments WHERE week_id=? ORDER BY id", (wid,))]
    c.close(); return rows


def _add_clean_member(name="老四"):
    c = connect()
    cur = c.execute("INSERT INTO members(name,active,data_quality) VALUES (?,1,'clean')", (name,))
    c.commit(); mid = cur.lastrowid; c.close(); return mid


def _add_clean_task(title="拖地"):
    c = connect()
    cur = c.execute("INSERT INTO tasks(title,weight,data_quality) VALUES (?,1,'clean')", (title,))
    c.commit(); tid = cur.lastrowid; c.close(); return tid


# --- 跳过空表 ---

def test_skip_empty_week_records_ledger(db):
    r = main.skip(1)  # 第12周，draft，无格子
    assert r["status"] == "skipped"
    assert r["phase_start"] == 0                       # 第一周，账本从零起
    assert r["slot_count"] == would_be_slots(3, 7)     # 3 个 clean 任务 × 7 天
    assert _assigns(1) == []                           # 跳过周不生成格子
    board = main.week_board(1)                         # 看板与周列表同钉：同一 status
    assert board["week"]["status"] == "skipped" and board["assignments"] == []
    assert _week(1)["status"] == "skipped"


# --- 相位连续 ---

def test_phase_continues_over_skipped_week(db):
    _add_clean_member()  # 4 个 clean 成员：21 格/周不再整除，相位偏移可见
    g1 = main.generate(1)
    assert g1["phase_start"] == 0 and g1["count"] == 21
    s2 = main.skip(2)                                  # 跳过第13周，不占人但占相位
    assert s2["phase_start"] == 21 and s2["slot_count"] == 21
    wid = main.add_week({"label": "第14周"})["id"]
    g3 = main.generate(wid)
    assert g3["phase_start"] == 42                     # 21 + 21，跳过周照常前进
    mids = [1, 2, 3, 4 + 1]                            # 种子 1/2/3 + 新成员 id=5
    expect = build_week_slots(mids, [1, 2, 3], days=7, phase=42)
    assert [a["member_id"] for a in _assigns(wid)] == [s["member_id"] for s in expect]
    assert _assigns(2) == []                           # 跳过周始终空表


def test_unskip_regenerate_starts_from_recorded_phase(db):
    _add_clean_member()
    main.generate(1)
    main.skip(2)
    u = main.unskip(2)                                 # 取消跳过 → 回 draft，不生成格子
    assert u["status"] == "draft" and u["phase_start"] == 21
    assert _assigns(2) == []
    _add_clean_task()                                  # 任务集变化也不改写记录相位
    g = main.generate(2)
    assert g["phase_start"] == 21                      # 从记录相位起算
    assert g["count"] == 28                            # slot_count 按当前应有格数刷新
    assert _week(2)["slot_count"] == 28
    mids = [1, 2, 3, 5]
    assert _assigns(2)[0]["member_id"] == mids[21 % len(mids)]


# --- 带格周 skip 取舍：清空格子 + 作废 pending 对调 ---

def test_skip_ready_week_clears_slots_and_voids_pending_swaps(db):
    main.generate(1)
    assert len(_assigns(1)) == 21
    sw = main.request_swap(1, main.SwapBody(a_day=0, a_task=1, b_day=0, b_task=2))
    assert sw["status"] == "pending"
    r = main.skip(1)                                   # 拍板：清空 + 作废，而非拒绝
    assert r["status"] == "skipped"
    assert _assigns(1) == []                           # 格子已清空
    c = connect(); row = c.execute("SELECT status FROM swap_requests WHERE id=?", (sw["id"],)).fetchone()
    c.close()
    assert row["status"] == "void"                     # pending 对调已作废
    with pytest.raises(HTTPException) as e:            # 作废后不可再确认改表
        main.confirm_swap(sw["id"])
    assert e.value.status_code == 400


# --- 状态机非法迁移 ---

def test_state_machine_rejects_illegal_transitions(db):
    main.skip(1)
    with pytest.raises(HTTPException) as e:
        main.generate(1)                               # 跳过周须先取消跳过
    assert e.value.status_code == 400 and "week_skipped" in e.value.detail
    with pytest.raises(HTTPException) as e:
        main.skip(1)                                   # 重复跳过非法
    assert "illegal_transition" in e.value.detail
    with pytest.raises(HTTPException) as e:
        main.unskip(2)                                 # draft 不能取消跳过
    assert "illegal_transition" in e.value.detail
    with pytest.raises(HTTPException) as e:
        main.request_swap(1, main.SwapBody(a_day=0, a_task=1, b_day=0, b_task=2))
    assert "week_skipped" in e.value.detail
    with pytest.raises(sk.IllegalTransition):
        sk.check_transition("ready", "draft")          # 状态机层面同样拒绝


# --- 只改家庭名不影响跳过标记 ---

def test_household_rename_keeps_skip_marker(db):
    main.skip(1)
    before = _week(1)
    main.put_settings({"household": "改名后的家"})
    after = _week(1)
    assert after["status"] == "skipped"
    assert after["phase_start"] == before["phase_start"]
    assert after["slot_count"] == before["slot_count"]
    assert main.get_settings()["household"] == "改名后的家"


# --- 相位账本纯函数 ---

def test_ledger_phase_sums_only_recorded_weeks():
    rows = [
        {"id": 1, "slot_count": 14},
        {"id": 2, "slot_count": None},                 # draft 周不计入
        {"id": 3, "slot_count": 7},
    ]
    assert ledger_phase(rows, 1) == 0
    assert ledger_phase(rows, 3) == 14
    assert ledger_phase(rows, 4) == 21


def test_would_be_slots():
    assert would_be_slots(3, 7) == 21
    assert would_be_slots(0, 7) == 0
