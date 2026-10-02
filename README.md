# Chorerota · 家庭值日轮转

底座：成员+任务 → round-robin 生成周表 → 申请对调 → 确认改表。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5100 |
| API | 10100 |

```bash
docker compose up --build
pytest backend/app/tests
```

种子含 clean/dirty。0-1 空桩：`streak_badge` / `chore_photo`。

## 整周跳过（skip_week）

- 周可 `skip`/`unskip`：跳过周不生成 assignments，`status='skipped'`，但 round-robin 相位仍按该周应有格数（天数 × clean 任务数）前进，后续周从累加相位承接。
- 相位账本：`weeks.phase_start` 首次生成/跳过时落账后不改写，取消跳过后重新生成从记录相位起算；`slot_count` 每次生成/跳过按当前格数刷新。
- 带格周取舍（前后端一致）：对已落格的周标记跳过 = **清空该周格子并作废其 pending 对调**（`status='void'`），而非拒绝。
- 状态机 `draft/ready → skipped → draft`，其余迁移 400；跳过周不可生成、不可申请对调。
- 分文件：状态机 `app/modules/skip_week/`、相位累加 `app/engines/phase.py`、生成入口 `app/main.py`。
