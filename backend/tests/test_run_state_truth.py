"""运行态真源四类夹具 + 两臂可分开验。

题面要求：
- 手改运行态列再推进启停
- 推进后再改列
- 并发双写
- 半截脏服役回滚
- 「列停灯成」读侧跟谁，两臂裁决要能分开验，且跟列与跟灯不得长期双账。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.db import db


def _raw_hand_edit(pod_id: int, state: str) -> None:
    """绕过接口直接改列：复刻旧病「手改运行态列」，不落任何单据/灯。"""
    with db(write=True) as conn:
        conn.execute("UPDATE pods SET run_state=? WHERE id=?", (state, pod_id))


# ---------------------------------------------------------------- 基本事务


def test_停止已停舱不谎点已完成灯(client, helper):
    """列说已停，停止单只能是「未生效」，不许出现列停灯成。"""
    out = helper.order(client, 1, "停止").json()
    assert out["status"] == "未生效"
    assert out["灯"] == "未生效"
    pods = helper.pods(client)
    assert pods["web-a"]["run_state"] == "已停止"
    assert pods["web-a"]["灯"] == "未生效"
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)


def test_启动失败整笔回滚(client, helper):
    """镜像未就绪：单与事件都标失败，运行态与配额不动。"""
    before = helper.quota(client)
    out = helper.order(client, 2, "启动").json()
    assert out["status"] == "失败" and out["note"] == "镜像未就绪"
    assert helper.pods(client)["worker-b"]["run_state"] == "已停止"
    assert helper.quota(client) == before


def test_启动已运行舱为未生效(client, helper):
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    again = helper.order(client, 1, "启动").json()
    assert again["status"] == "未生效" and again["灯"] == "未生效"
    assert helper.pods(client)["web-a"]["run_state"] == "运行中"
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.7)


# ---------------------------------------------------------------- 手改列再推进


def test_手改运行态列再推进启停(client, helper):
    """臂A：手改列即权威；随后停止单必须真的把运行态改回已停并点已完成。"""
    r = helper.hand_edit(client, 1, "运行中", note="人工置运行中")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "已完成" and body["后运行态"] == "运行中"
    pods = helper.pods(client)
    assert pods["web-a"]["run_state"] == "运行中"
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.7)  # 占用同步回补

    out = helper.order(client, 1, "停止").json()
    assert out["status"] == "已完成" and out["灯"] == "已完成"
    pods = helper.pods(client)
    assert pods["web-a"]["run_state"] == "已停止"
    assert pods["web-a"]["灯"] == "已完成" and pods["web-a"]["灯态"] == "已停止"
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)


# ---------------------------------------------------------------- 推进后再改列


def test_推进后再改列(client, helper):
    """臂A：启动成功后再手改回已停；版本前移、配额归还，灯随附件同向。"""
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    assert helper.pods(client)["web-a"]["列版本"] == 1

    stale = helper.hand_edit(client, 1, "已停止", expect_rev=0)
    assert stale.status_code == 409
    assert stale.json()["detail"]["当前版本"] == 1

    r = helper.hand_edit(client, 1, "已停止", expect_rev=1, note="人工停机")
    assert r.status_code == 200, r.text
    assert r.json()["后运行态"] == "已停止"
    pods, align = helper.align(client)
    assert helper.pods(client)["web-a"]["run_state"] == "已停止"
    assert align["舱体投影"][0]["灯"] == "已完成"
    assert align["舱体投影"][0]["灯态"] == "已停止"
    assert align["舱体投影"][0]["漂移"] is False
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)

    # 之后再开停止单：运行态未变，只落「未生效」，不会补出第二条已完成灯。
    out = helper.order(client, 1, "停止").json()
    assert out["status"] == "未生效"
    assert helper.orders_of(client, 1)[0]["status"] == "未生效"


# ---------------------------------------------------------------- 并发双写


def test_并发双写启动只成一单(client, helper):
    """两线程同时启动同舱：写锁串行，恰一单已完成、一单未生效，配额只占一份。"""
    results: list[dict] = []
    barrier = threading.Barrier(2)

    def fire():
        c = TestClient(app_main.app)
        barrier.wait()
        results.append(c.post("/api/启停单", json={"pod_id": 1, "action": "启动"}).json())
        c.close()

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(r["status"] for r in results)
    assert statuses == ["已完成", "未生效"], results
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.7)
    done = [o for o in helper.orders_of(client, 1) if o["status"] == "已完成"]
    assert len(done) == 1
    assert helper.pods(client)["web-a"]["run_state"] == "运行中"


def test_并发启动停止后运行态与单灯一致(client, helper):
    """启动与停止对撞：最终运行态必须等于最后一笔生效单的结果态，配额不留半份。"""
    barrier = threading.Barrier(2)

    def fire(action, out):
        c = TestClient(app_main.app)
        barrier.wait()
        out.append(c.post("/api/启停单", json={"pod_id": 1, "action": action}).json())
        c.close()

    out: list[dict] = []
    ts = [threading.Thread(target=fire, args=("启动", out)), threading.Thread(target=fire, args=("停止", out))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    pod = helper.pods(client)["web-a"]
    orders = helper.orders_of(client, 1)
    effective = [o for o in orders if o["生效"]]
    assert effective, orders
    last_effective = effective[0]
    assert pod["run_state"] == last_effective["result_state"]
    assert pod["灯"] == last_effective["灯"]
    used = helper.quota(client)["cpu_used"]
    assert used in (pytest.approx(1.2), pytest.approx(1.7))
    assert pod["run_state"] == ("运行中" if used == pytest.approx(1.7) else "已停止")


# ---------------------------------------------------------------- 半截回滚


def test_半截脏服役整笔回滚(client, helper, monkeypatch):
    """运行态已写、单未落库时抛错：同笔回滚，不留半截脏服役。"""
    import app.routers.orders as orders_mod

    def boom(*a, **kw):
        raise RuntimeError("注入写单失败")

    monkeypatch.setattr(orders_mod, "_record", boom)
    with pytest.raises(RuntimeError):
        client.post("/api/启停单", json={"pod_id": 1, "action": "启动"})
    monkeypatch.undo()

    pod = helper.pods(client)["web-a"]
    assert pod["run_state"] == "已停止" and pod["列版本"] == 0
    assert pod["quota_held"] == 0
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)
    assert helper.orders_of(client, 1) == []
    events = client.get("/api/事件").json()
    assert all("启动" not in (e["detail"] or "") for e in events)

    # 回滚后同一笔仍可正常成功，说明没有残留锁或脏行。
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"


def test_半截回滚不吞已提交的配额(client, helper, monkeypatch):
    """失败注入点若在配额已加之后，配额也必须跟着回滚。"""
    import app.routers.orders as orders_mod

    orig = orders_mod.apply_run_state

    def boom_after(conn, pod, target, at):
        res = orig(conn, pod, target, at)  # 先写运行态 + 配额
        raise RuntimeError("注入半截脏服役")

    monkeypatch.setattr(orders_mod, "apply_run_state", boom_after)
    with pytest.raises(RuntimeError):
        client.post("/api/启停单", json={"pod_id": 1, "action": "启动"})
    monkeypatch.undo()

    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)
    assert helper.pods(client)["web-a"]["run_state"] == "已停止"
    assert helper.orders_of(client, 1) == []


# ---------------------------------------------------------------- 两臂分开验


def test_列停灯成两臂裁决分开验(client, helper):
    """构造「列已停、灯已完成（运行中）」：臂A跟列，臂B跟灯，读侧结论必须不同。"""
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    _raw_hand_edit(1, "已停止")  # 旧病式手改列，不落单

    helper.arm(client, "列")
    pods_a, align_a = helper.align(client)
    assert align_a["真源"] == "运行态列"
    assert align_a["舱体投影"][0]["运行"] == "已停止"
    assert align_a["舱体投影"][0]["漂移"] is True
    assert align_a["舱体投影"][0]["漂移类型"] == "灯附件过期"
    assert align_a["舱体投影"][0]["灯"] == "已完成"

    helper.arm(client, "灯")
    pods_b, align_b = helper.align(client)
    assert align_b["真源"] == "启停单已完成灯"
    assert align_b["舱体投影"][0]["运行"] == "运行中"
    assert align_b["舱体投影"][0]["依据"].startswith("启停单#")
    assert align_b["舱体投影"][0]["漂移"] is True
    assert align_b["舱体投影"][0]["漂移类型"] == "缓存偏差"

    assert align_a["舱体投影"][0]["运行"] != align_b["舱体投影"][0]["运行"]


def test_臂A推进启停不让灯偷改列(client, helper):
    """臂A下旧灯不得改写已刷运行态：手改列停后，启停推进以列为准。"""
    helper.arm(client, "列")
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    helper.hand_edit(client, 1, "已停止", expect_rev=1)
    # 此刻灯重放（旧单）会是运行中，但臂A读侧只跟列。
    pods, align = helper.align(client)
    assert align["舱体投影"][0]["运行"] == "已停止"
    # 再推一枚「启动」单：必须真的从列态启动，而不是被旧灯当作已在运行。
    out = helper.order(client, 1, "启动").json()
    assert out["status"] == "已完成" and out["前运行态"] == "已停止"
    assert helper.pods(client)["web-a"]["run_state"] == "运行中"


def test_臂B改列必须纠偏否则拒绝(client, helper):
    """臂B：缓存不是真源，直接手改列 409；声明纠偏后同笔翻灯，不留双账。"""
    helper.arm(client, "灯")
    r = helper.hand_edit(client, 1, "运行中")
    assert r.status_code == 409
    assert r.json()["detail"]["需纠偏"] is True
    assert r.json()["detail"]["灯重放"] == "已停止"

    r = helper.hand_edit(client, 1, "运行中", 纠偏=True, note="当场纠偏")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "纠偏"
    pods, align = helper.align(client)
    assert align["舱体投影"][0]["运行"] == "运行中"
    assert align["舱体投影"][0]["灯"] == "纠偏"
    assert align["舱体投影"][0]["漂移"] is False
    assert helper.pods(client)["web-a"]["列"] == "运行中"


def test_臂B读侧把缓存偏差当场刷平(client, helper):
    """臂B：运行态列被旁路改脏后，下一笔启停推进同笔刷回，长期不留两套观感。"""
    helper.arm(client, "灯")
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    _raw_hand_edit(1, "已停止")  # 缓存被弄脏，灯仍说运行中

    align = helper.align(client)[1]
    assert align["舱体投影"][0]["运行"] == "运行中"
    assert align["舱体投影"][0]["漂移"] is True

    out = helper.order(client, 1, "停止").json()
    assert out["status"] == "已完成" and out["后运行态"] == "已停止"
    pods = helper.pods(client)
    assert pods["web-a"]["列"] == "已停止"  # 缓存已被同笔刷平
    assert pods["web-a"]["漂移"] is False
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)


def test_臂B脏缓存同值纠偏仍刷平(client, helper):
    """臂B：列被旁路改脏成与目标同值，纠偏单仍须生效并刷平缓存/配额。"""
    helper.arm(client, "灯")
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    _raw_hand_edit(1, "已停止")  # 列已脏成 已停止，灯仍说运行中

    r = helper.hand_edit(client, 1, "已停止", 纠偏=True, note="当场纠偏")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "纠偏"
    pods, align = helper.align(client)
    assert align["舱体投影"][0]["运行"] == "已停止"
    assert align["舱体投影"][0]["灯"] == "纠偏"
    assert align["舱体投影"][0]["漂移"] is False
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.2)


def test_臂B同态纠偏为未生效且不推版本(client, helper):
    """臂B：灯已说运行中，再纠偏成运行中不产生翻转，只落未生效单。"""
    helper.arm(client, "灯")
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    rev = helper.pods(client)["web-a"]["列版本"]
    r = helper.hand_edit(client, 1, "运行中", 纠偏=True, note="复核")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "未生效" and r.json()["灯"] == "未生效"
    pods = helper.pods(client)
    assert pods["web-a"]["列版本"] == rev
    assert pods["web-a"]["漂移"] is False
    assert helper.quota(client)["cpu_used"] == pytest.approx(1.7)


def test_切臂落事件痕且读侧即时生效(client, helper):
    helper.arm(client, "灯")
    events = client.get("/api/事件").json()
    assert any(e["kind"] == "真源" and "启停单已完成灯" in e["detail"] for e in events)
    assert helper.align(client)[1]["真源代码"] == "灯"
    helper.arm(client, "列")
    assert helper.align(client)[1]["真源代码"] == "列"


# ---------------------------------------------------------------- 互证


def test_四处互证同口径(client, helper):
    """舱体列、启停单灯、对读屏运行格、事件旁读必须对同一运行态说同一件事。"""
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"

    pod = helper.pods(client)["web-a"]
    align_rows, align = helper.align(client)
    orders = helper.orders_of(client, 1)
    events = client.get("/api/事件").json()

    assert pod["run_state"] == align_rows["web-a"]["运行"] == "运行中"
    assert pod["灯"] == orders[0]["灯"] == align_rows["web-a"]["灯"] == "已完成"
    assert orders[0]["result_state"] == align_rows["web-a"]["运行"]

    latest = [e for e in events if e["kind"] == "启停单"][0]
    assert f"启动 已停止→运行中 [已完成]" in latest["detail"]
    assert f"真源={align['真源']}" in latest["detail"]


def test_跨舱互不影响(client, helper):
    """一舱推进不得改另一舱运行态与附件。"""
    assert helper.order(client, 1, "启动").json()["status"] == "已完成"
    pods = helper.pods(client)
    assert pods["web-a"]["run_state"] == "运行中"
    assert pods["worker-b"]["run_state"] == "已停止"
    assert pods["worker-b"]["列版本"] == 0
