from __future__ import annotations
from fastapi import APIRouter
from app.db import db
from app.services.common import rows
from app.services.run_state import current_arm, fetch_orders, resolve_row

router = APIRouter(tags=["舱体"])


@router.get("/舱体")
def list_pods():
    """舱体运行态列：`运行` 按选定真源重放，`列` 是原样列值，附件灯与漂移同时给出。"""
    arm = current_arm()
    with db() as conn:
        pods = rows(
            conn.execute(
                """
                SELECT p.*, i.name AS image_name, i.tag AS image_tag, i.pull_state,
                       pr.color AS probe_color, pr.fail_streak
                FROM pods p
                LEFT JOIN images i ON i.id = p.image_id
                LEFT JOIN probes pr ON pr.pod_id = p.id
                ORDER BY p.id
                """
            )
        )
        out = []
        for p in pods:
            proj = resolve_row(p, fetch_orders(conn, p["id"]), arm)
            p["run_state"] = proj["运行"]
            p["列"] = proj["列"]
            p["列版本"] = proj["列版本"]
            p["真源"] = proj["真源"]
            p["灯"] = proj["灯"]
            p["灯态"] = proj["灯态"]
            p["漂移"] = proj["漂移"]
            p["漂移类型"] = proj["漂移类型"]
            p["漂移说明"] = proj["漂移说明"]
            out.append(p)
        return out
