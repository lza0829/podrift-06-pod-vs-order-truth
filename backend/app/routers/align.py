from __future__ import annotations
from fastapi import APIRouter
from app.db import db
from app.services.common import rows
from app.services.run_state import (
    ARM_LANE,
    ARM_LAMP,
    ARM_COLUMN,
    current_arm,
    fetch_orders,
    resolve_row,
)

router = APIRouter(tags=["对读屏"])


@router.get("/对读")
def align_view():
    """对读屏：运行格只听选定真源，灯与事件痕作旁读附件，漂移当场标出。"""
    arm = current_arm()
    with db() as conn:
        base = rows(
            conn.execute(
                """
                SELECT p.id, p.name, p.run_state, p.run_state_rev, pr.color AS probe_color,
                       pr.fail_streak, i.pull_state
                FROM pods p
                LEFT JOIN probes pr ON pr.pod_id = p.id
                LEFT JOIN images i ON i.id = p.image_id
                ORDER BY p.id
                """
            )
        )
        pods = []
        for p in base:
            orders = fetch_orders(conn, p["id"])
            proj = resolve_row(p, orders, arm)
            latest = orders[0] if orders else None
            pods.append({
                **p,
                "运行": proj["运行"],
                "真源": proj["真源"],
                "依据": proj["依据"],
                "依据单号": proj["依据单号"],
                "列": proj["列"],
                "列版本": proj["列版本"],
                "灯": proj["灯"],
                "灯态": proj["灯态"],
                "灯说明": proj["灯说明"],
                "漂移": proj["漂移"],
                "漂移类型": proj["漂移类型"],
                "漂移说明": proj["漂移说明"],
                "last_order_status": latest["status"] if latest else None,
                "last_order_note": latest["note"] if latest else None,
                "last_order_id": latest["id"] if latest else None,
            })
        quota = dict(conn.execute("SELECT * FROM quotas WHERE id=1").fetchone())
        policy = dict(conn.execute("SELECT * FROM restart_policy WHERE id=1").fetchone())
        return {
            "真源": ARM_LANE[arm],
            "真源代码": arm,
            "可选臂": {ARM_COLUMN: ARM_LANE[ARM_COLUMN], ARM_LAMP: ARM_LANE[ARM_LAMP]},
            "舱体投影": pods,
            "配额": quota,
            "重启策": policy,
        }
