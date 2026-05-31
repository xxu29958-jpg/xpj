"""ADR-0038 软删除保留窗口策略(单一真相源)。

软删除的 alias / rule 在 SOFT_DELETE_RETENTION_MINUTES 后由 cleanup 永久 purge;在此之前
undo/restore 可恢复。purge(cleanup)与 restore(undo)必须共用**同一个**窗口——否则 cleanup
滞后时超期行仍能被 undo 恢复(codex P1)。本模块把窗口 + 判定收到一处,两侧都引用。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.time_service import ensure_utc, now_utc

# 服务端保留窗口:软删除行被永久 purge 前的宽限期。客户端 undo banner 是更短的 UX
# 窗口(~5s);这是服务端 grace period,过后行就没了。
SOFT_DELETE_RETENTION_MINUTES = 5
SOFT_DELETE_RETENTION = timedelta(minutes=SOFT_DELETE_RETENTION_MINUTES)


def is_within_undo_window(deleted_at: datetime | None) -> bool:
    """软删除行是否仍在 undo 保留窗口内。

    ``None``(未软删除)→ False。naive datetime 视为 UTC(SQLite 存 naive)。undo/restore
    路径用它挡住「超期但 cleanup 还没 purge」的行,使恢复语义与 purge 一致。
    """
    aware = ensure_utc(deleted_at)
    if aware is None:
        return False
    return now_utc() - aware <= SOFT_DELETE_RETENTION
