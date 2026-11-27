from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db
from app.services.common import now_iso, rows
from app.services.run_state import (
    ARM_LAMP,
    RUNNING,
    STOPPED,
    apply_run_state,
    arm_lane,
    current_arm,
    fetch_orders,
    lamp_of,
    refresh_cache,
    replay_state,
)

router = APIRouter(tags=["启停单"])

_START_ALIASES = ("启动", "start", "Start")
_STOP_ALIASES = ("停止", "stop", "Stop")
_MANUAL_ACTION = "手改运行态"


class OrderIn(BaseModel):
    pod_id: int
    action: str  # 启动 | 停止
    target_image_id: int | None = None


class RunStateIn(BaseModel):
    run_state: str
    note: str = ""
    expect_rev: int | None = None
    # 臂B下改列必须声明为纠偏，才能当场翻灯；臂A下为权威改写，无需声明。
    纠偏: bool = False


def _pod(conn, pod_id: int):
    return conn.execute("SELECT * FROM pods WHERE id=?", (pod_id,)).fetchone()


def _truth_state(conn, pod, arm: str) -> str:
    """按选定真源判定当前运行态。臂A读列；臂B按单据重放。"""
    if arm == ARM_LAMP:
        return replay_state(pod, fetch_orders(conn, pod["id"]))["态"]
    return pod["run_state"]


def _record(conn, *, pod_id: int, action: str, status: str, note: str,
            prev: str, result: str | None, rev: int | None, img_id: int | None,
            arm: str) -> tuple[int, str]:
    at = now_iso()
    cur = conn.execute(
        """
        INSERT INTO start_orders(pod_id, action, target_image_id, status, note,
                                 prev_state, result_state, state_rev, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (pod_id, action, img_id, status, note, prev, result, rev, at),
    )
    detail = f"{action} {prev}→{result or '—'} [{status}] rev={rev} 真源={arm_lane(arm)}"
    if note:
        detail += f" · {note}"
    kind = "手改运行态" if action == _MANUAL_ACTION else "启停单"
    conn.execute(
        "INSERT INTO events(kind, ref, detail, at) VALUES (?,?,?,?)",
        (kind, str(cur.lastrowid), detail, at),
    )
    return cur.lastrowid, at


@router.get("/启停单")
def list_orders():
    with db() as conn:
        out = rows(conn.execute("SELECT * FROM start_orders ORDER BY id DESC"))
    for o in out:
        lamp = lamp_of(o)
        o["灯"] = lamp["灯"]
        o["灯态"] = lamp["态"]
        o["灯说明"] = lamp["说明"]
        o["生效"] = lamp["生效"]
    return out


@router.post("/启停单")
def create_order(body: OrderIn):
    """运行态改写与启停单推进同笔成败：要么整笔提交，要么整笔回滚。

    读侧按选定真源先判当前运行态，再在同一写锁内推进：
    - 臂A：以运行态列为准；列说已停止，停止单就是「未生效」，不许点「已完成」。
    - 臂B：以启停单灯重放为准；列只是缓存，推进前先把缓存刷回重放结论。
    """
    action = (body.action or "").strip()
    stored = "启动" if action in _START_ALIASES else ("停止" if action in _STOP_ALIASES else action)
    arm = current_arm()
    with db(write=True) as conn:
        pod = _pod(conn, body.pod_id)
        if not pod:
            raise HTTPException(status_code=404, detail="舱体不存在")
        img_id = body.target_image_id or pod["image_id"]
        if arm == ARM_LAMP:
            truth = _truth_state(conn, pod, arm)
            if truth != pod["run_state"]:
                # 臂B：缓存与灯不一致时，先同笔把缓存刷回重放结论，避免长期双账。
                refresh_cache(conn, pod, truth, now_iso())
                pod = _pod(conn, body.pod_id)
        truth = _truth_state(conn, pod, arm)

        if stored == "启动":
            status, note, result = "未生效", "已在运行中，运行态未变", truth
            if truth != RUNNING:
                img = conn.execute("SELECT * FROM images WHERE id=?", (img_id,)).fetchone()
                if not img or img["pull_state"] != "已就绪":
                    status, note, result = "失败", "镜像未就绪", truth
                else:
                    q = conn.execute("SELECT * FROM quotas WHERE id=1").fetchone()
                    need_cpu = float(pod["cpu_quota"])
                    need_mem = int(pod["mem_quota_mb"])
                    if float(q["cpu_used"]) + need_cpu > float(q["cpu_limit"]) or int(q["mem_used_mb"]) + need_mem > int(q["mem_limit_mb"]):
                        status, note, result = "失败", "配额不足", truth
                    else:
                        step = apply_run_state(conn, pod, RUNNING, now_iso())
                        if step["changed"]:
                            status, note, result = "已完成", "启动成功", RUNNING
                        else:  # 理论上不可达：truth 已判非运行中
                            status, note, result = "未生效", "运行态未变", truth
                        pod = _pod(conn, body.pod_id)
        elif stored == "停止":
            if truth != RUNNING:
                status, note, result = "未生效", "停止前并非运行中，运行态未变", truth
            else:
                step = apply_run_state(conn, pod, STOPPED, now_iso())
                status = "已完成" if step["changed"] else "未生效"
                note = "停止成功" if step["changed"] else "运行态未变"
                result = STOPPED if step["changed"] else truth
                pod = _pod(conn, body.pod_id)
        else:
            status, note, result = "失败", f"未知动作:{action}", truth

        rev = int(pod["run_state_rev"] or 0)
        order_id, _ = _record(
            conn, pod_id=body.pod_id, action=stored, status=status, note=note,
            prev=truth, result=result, rev=rev, img_id=img_id, arm=arm,
        )
        return {
            "id": order_id,
            "status": status,
            "note": note,
            "真源": arm_lane(arm),
            "前运行态": truth,
            "后运行态": result,
            "列": pod["run_state"],
            "列版本": rev,
            "灯": lamp_of({
                "status": status, "action": stored, "prev_state": truth,
                "result_state": result, "note": note,
            })["灯"],
        }


@router.post("/舱体/{pod_id}/运行态")
def edit_run_state(pod_id: int, body: RunStateIn):
    """手改运行态列。

    - 臂A：列是唯一真源，手改即权威改写；同笔落一张「手改运行态」附件单与事件痕。
    - 臂B：列只是缓存，手改必须声明「纠偏」，否则拒绝并提示当场纠偏；
      声明纠偏后同笔翻灯 + 刷缓存，禁止长期两套运行态观感。
    """
    target = (body.run_state or "").strip()
    if target not in (RUNNING, STOPPED):
        raise HTTPException(status_code=422, detail=f"未知运行态:{target}")
    arm = current_arm()
    with db(write=True) as conn:
        pod = _pod(conn, pod_id)
        if not pod:
            raise HTTPException(status_code=404, detail="舱体不存在")
        if body.expect_rev is not None and int(pod["run_state_rev"] or 0) != int(body.expect_rev):
            raise HTTPException(
                status_code=409,
                detail={
                    "冲突": "列版本已变",
                    "期望版本": body.expect_rev,
                    "当前版本": int(pod["run_state_rev"] or 0),
                    "当前列": pod["run_state"],
                },
            )
        truth = _truth_state(conn, pod, arm)
        if arm == ARM_LAMP and not body.纠偏:
            drift = truth != pod["run_state"]
            raise HTTPException(
                status_code=409,
                detail={
                    "需纠偏": True,
                    "说明": "所选真源为启停单灯；改列必须先纠偏，否则读侧仍按灯重放",
                    "列": pod["run_state"],
                    "灯重放": truth,
                    "缓存偏差": drift,
                },
            )

        prev_truth = truth
        if arm == ARM_LAMP:
            # 臂B：缓存只是附件，必须无条件刷成目标态；灯是否翻转由单子快照裁定，
            # 所以即便列已被旁路改脏成同一值，纠偏单仍然生效并把缓存刷平。
            refresh_cache(conn, pod, target, now_iso())
            flipped = target != prev_truth
            status = "纠偏" if flipped else "未生效"
            note = (body.note or "").strip() or ("纠偏运行态" if flipped else "运行态未变")
        else:
            step = apply_run_state(conn, pod, target, now_iso())
            status = "已完成" if step["changed"] else "未生效"
            note = (body.note or "").strip() or ("手改运行态" if step["changed"] else "运行态未变")

        pod = _pod(conn, pod_id)
        rev = int(pod["run_state_rev"] or 0)
        result = target if status in ("纠偏", "已完成") else prev_truth
        order_id, _ = _record(
            conn, pod_id=pod_id, action=_MANUAL_ACTION, status=status, note=note,
            prev=prev_truth, result=result, rev=rev, img_id=pod["image_id"], arm=arm,
        )
        return {
            "id": order_id,
            "status": status,
            "note": note,
            "真源": arm_lane(arm),
            "前运行态": prev_truth,
            "后运行态": pod["run_state"],
            "列": pod["run_state"],
            "列版本": rev,
            "灯": lamp_of({
                "status": status, "action": _MANUAL_ACTION, "prev_state": prev_truth,
                "result_state": result, "note": note,
            })["灯"],
        }
