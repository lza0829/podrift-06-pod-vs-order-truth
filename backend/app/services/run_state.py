"""运行态真源：单笔事务推进 + 按选定真源重放。

两臂定义（题面要求二选一，实现上可切换以便分开验）：

- 臂A `列`：`pods.run_state` 是唯一真源；启停单灯与事件痕只是附件，不允许用单灯/流水
  偷偷改写已经刷新的运行态。手改运行态列即为权威改写。
- 臂B `灯`：启停单「已完成」灯是唯一真源，`pods.run_state` 只是缓存；读侧一律按单据
  重放。手改运行态列必须走纠偏单当场翻灯，否则读侧只认灯并标记缓存偏差。

两种臂共用同一套落库事务：运行态改写与启停单推进同笔提交，任一失败整笔回滚。
"""
from __future__ import annotations

import os

RUNNING = "运行中"
STOPPED = "已停止"
ARM_COLUMN = "列"
ARM_LAMP = "灯"
ARM_LANE = {
    ARM_COLUMN: "运行态列",
    ARM_LAMP: "启停单已完成灯",
}
_TRUTH_ENV = "PODRIFT_TRUTH"


def normalize_arm(raw: str | None) -> str | None:
    val = (raw or "").strip().lower()
    if val in ("b", "灯", "lamp", "order", "启停单", "启停单已完成灯"):
        return ARM_LAMP
    if val in ("a", "列", "column", "运行态列", "运行态列口径"):
        return ARM_COLUMN
    return None


def _stored_arm() -> str | None:
    """舱规里可切换的选定真源：运行态真源=列|灯。"""
    from app.db import db

    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", ("运行态真源",)).fetchone()
        return normalize_arm(row["value"] if row else None)
    except Exception:
        return None


def current_arm() -> str:
    """选定真源：环境变量 PODRIFT_TRUTH 优先，其次舱规「运行态真源」，默认臂A。"""
    return normalize_arm(os.environ.get(_TRUTH_ENV)) or _stored_arm() or ARM_COLUMN


def store_arm(conn, arm: str | None) -> str:
    """在调用方事务内落当前所选真源。"""
    picked = normalize_arm(arm) or ARM_COLUMN
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("运行态真源", picked),
    )
    return picked


def set_arm(arm: str) -> str:
    from app.db import db

    with db(write=True) as conn:
        return store_arm(conn, arm)


def arm_lane(arm: str | None = None) -> str:
    return ARM_LANE[arm or current_arm()]


def _get(order, key: str, default=None):
    if order is None:
        return default
    try:
        return order[key]
    except (KeyError, IndexError):
        return default


def lamp_of(order) -> dict:
    """由单行推灯：只有运行态确实被改写的单才点亮「已完成」。

    - 失败：前置校验没过，运行态未动。
    - 未生效：单子受理了但运行态本就无需改变（如舱体已停还要停），不许骗成「已完成」。
    - 已完成：prev_state 与 result_state 确实翻转，且结果态可判定。
    - 纠偏：臂B下手改运行态列的纠正单据，等价于一次权威翻转。
    """
    if order is None:
        return {"灯": None, "生效": False, "态": None, "说明": "无启停单"}
    status = _get(order, "status")
    action = _get(order, "action")
    prev = _get(order, "prev_state")
    result = _get(order, "result_state")
    if status == "失败":
        return {"灯": "失败", "生效": False, "态": None, "说明": _get(order, "note") or "启停失败"}
    if status == "未生效":
        return {"灯": "未生效", "生效": False, "态": None, "说明": _get(order, "note") or "运行态未变"}
    if status == "纠偏":
        if result in (RUNNING, STOPPED) and prev != result:
            return {"灯": "纠偏", "生效": True, "态": result, "说明": _get(order, "note") or "纠偏运行态"}
        return {"灯": "未生效", "生效": False, "态": None, "说明": _get(order, "note") or "运行态未变"}
    if status != "已完成":
        return {"灯": status, "生效": False, "态": None, "说明": _get(order, "note") or "在途"}
    if result not in (RUNNING, STOPPED):
        return {"灯": "未生效", "生效": False, "态": None, "说明": "历史单缺运行态快照，无法重放"}
    if prev == result:
        return {"灯": "未生效", "生效": False, "态": None, "说明": "运行态未变，不点已完成灯"}
    if action == "停止" and prev != RUNNING:
        return {"灯": "未生效", "生效": False, "态": None, "说明": "停止前并非运行中"}
    if action == "启动" and result != RUNNING:
        return {"灯": "未生效", "生效": False, "态": None, "说明": "启动后并非运行中"}
    return {"灯": "已完成", "生效": True, "态": result, "说明": _get(order, "note") or ""}


def replay_state(pod, orders) -> dict:
    """臂B读侧：按单据（id 倒序）重放当前运行态。

    取最近一张「生效」单的结果态；没有生效单时以运行态列作为基线快照。
    """
    for order in orders or []:
        lamp = lamp_of(order)
        if lamp["生效"] and lamp["态"] in (RUNNING, STOPPED):
            return {"态": lamp["态"], "依据": f"启停单#{_get(order, 'id')}", "单号": _get(order, "id")}
    return {"态": _get(pod, "run_state"), "依据": "运行态列基线（无生效单）", "单号": None}


def resolve_row(pod, orders=None, arm: str | None = None) -> dict:
    """合成一行读侧投影：单一运行格 + 真源出处 + 附件灯/缓存偏差。"""
    arm = arm or current_arm()
    orders = orders or []
    latest = orders[0] if orders else None
    lamp = lamp_of(latest)
    if arm == ARM_LAMP:
        replay = replay_state(pod, orders)
        truth = replay["态"]
        basis = replay["依据"]
        basis_order = replay["单号"]
        drift = truth != _get(pod, "run_state")
        drift_kind = "缓存偏差" if drift else ""
        drift_note = (
            f"运行态列缓存为 {_get(pod, 'run_state')}，按灯重放应为 {truth}；可当场纠偏"
            if drift
            else ""
        )
    else:
        truth = _get(pod, "run_state")
        basis = "运行态列"
        basis_order = None
        lamp_state = lamp["态"] if lamp["生效"] else None
        drift = bool(lamp_state and lamp_state != truth)
        drift_kind = "灯附件过期" if drift else ""
        drift_note = (
            f"启停单灯（{lamp_state}）早于手改运行态（{truth}）；读侧只跟列，灯仅作附件"
            if drift
            else ""
        )
    return {
        "运行": truth,
        "真源": ARM_LANE[arm],
        "依据": basis,
        "依据单号": basis_order,
        "列": _get(pod, "run_state"),
        "列版本": _get(pod, "run_state_rev", 0),
        "灯": lamp["灯"],
        "灯态": lamp["态"],
        "灯说明": lamp["说明"],
        "漂移": drift,
        "漂移类型": drift_kind,
        "漂移说明": drift_note,
    }


def fetch_orders(conn, pod_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM start_orders WHERE pod_id=? ORDER BY id DESC", (pod_id,))]


def apply_run_state(conn, pod, target: str, at: str) -> dict:
    """在现有（已开启的）事务内翻运行态列，并同步配额占用。

    返回 prev / rev / changed。调用方必须已经在 `db(write=True)` 里。
    """
    if target not in (RUNNING, STOPPED):
        raise ValueError(f"未知运行态:{target}")
    prev = pod["run_state"]
    rev = int(pod["run_state_rev"] or 0)
    if prev == target:
        return {"prev": prev, "rev": rev, "changed": False}
    held = int(pod["quota_held"] or 0) if "quota_held" in pod.keys() else 0
    delta_cpu = float(pod["cpu_quota"])
    delta_mem = int(pod["mem_quota_mb"])
    if target == RUNNING and not held:
        conn.execute(
            "UPDATE quotas SET cpu_used=cpu_used+?, mem_used_mb=mem_used_mb+? WHERE id=1",
            (delta_cpu, delta_mem),
        )
        held = 1
    elif target == STOPPED and held:
        conn.execute(
            "UPDATE quotas SET cpu_used=MAX(0, cpu_used-?), mem_used_mb=MAX(0, mem_used_mb-?) WHERE id=1",
            (delta_cpu, delta_mem),
        )
        held = 0
    conn.execute(
        "UPDATE pods SET run_state=?, run_state_rev=run_state_rev+1, run_state_at=?, quota_held=? WHERE id=?",
        (target, at, held, pod["id"]),
    )
    return {"prev": prev, "rev": rev + 1, "changed": True}


def refresh_cache(conn, pod, target: str, at: str) -> dict:
    """臂B：把运行态列缓存刷回重放结论（无新增单据，不算一次翻转）。

    列值若已与结论一致就只做配额对账，不推版本号；返回到账后的 held 供调用方参考。
    """
    if target not in (RUNNING, STOPPED):
        raise ValueError(f"未知运行态:{target}")
    prev = pod["run_state"]
    held = int(pod["quota_held"] or 0) if "quota_held" in pod.keys() else 0
    if target == RUNNING and not held:
        conn.execute(
            "UPDATE quotas SET cpu_used=cpu_used+?, mem_used_mb=mem_used_mb+? WHERE id=1",
            (float(pod["cpu_quota"]), int(pod["mem_quota_mb"])),
        )
        held = 1
    elif target == STOPPED and held:
        conn.execute(
            "UPDATE quotas SET cpu_used=MAX(0, cpu_used-?), mem_used_mb=MAX(0, mem_used_mb-?) WHERE id=1",
            (float(pod["cpu_quota"]), int(pod["mem_quota_mb"])),
        )
        held = 0
    if prev != target:
        conn.execute(
            "UPDATE pods SET run_state=?, run_state_rev=run_state_rev+1, run_state_at=?, quota_held=? WHERE id=?",
            (target, at, held, pod["id"]),
        )
    elif held != int(pod["quota_held"] or 0):
        conn.execute("UPDATE pods SET quota_held=? WHERE id=?", (held, pod["id"]))
    changed = prev != target
    return {"prev": prev, "rev": int(pod["run_state_rev"] or 0) + (1 if changed else 0),
            "changed": changed, "held": held}
