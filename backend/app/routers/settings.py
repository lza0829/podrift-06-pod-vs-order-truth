from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from app.db import db
from app.services.common import rows
from app.services.run_state import ARM_LANE, store_arm

router = APIRouter(tags=["舱规"])


class SettingIn(BaseModel):
    key: str
    value: str


@router.get("/舱规")
def list_settings():
    with db() as conn:
        return rows(conn.execute("SELECT * FROM settings ORDER BY key"))


@router.post("/舱规")
def set_setting(body: SettingIn):
    if body.key == "运行态真源":
        # 切臂与事件痕同笔：读侧即刻按新臂重放，不靠改代码开关。
        with db(write=True) as conn:
            arm = store_arm(conn, body.value)
            conn.execute(
                "INSERT INTO events(kind, ref, detail, at) VALUES (?,?,?,?)",
                ("真源", "运行态", f"选定真源改为 {ARM_LANE[arm]}", _now()),
            )
        return {"ok": True, "运行态真源": ARM_LANE[arm], "真源代码": arm}
    with db(write=True) as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (body.key, body.value),
        )
    return {"ok": True}


@router.get("/事件")
def list_events():
    with db() as conn:
        return rows(conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 80"))


def _now() -> str:
    from app.services.common import now_iso

    return now_iso()
