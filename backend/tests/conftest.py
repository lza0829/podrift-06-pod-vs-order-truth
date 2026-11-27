from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 测试库与其他进程隔离；真源不用环境变量钉死，改为按舱规切换，正好验两臂。
os.environ.pop("PODRIFT_TRUTH", None)
os.environ["PODRIFT_DB"] = str(Path(tempfile.mkdtemp(prefix="podrift-test-")) / "podrift.db")
# 夹具只验事务语义，不必每次提交都 fsync 到盘；生产默认仍是 FULL。
os.environ["PODRIFT_DB_SYNC"] = "OFF"

from fastapi.testclient import TestClient  # noqa: E402

from app import main as app_main  # noqa: E402
import app.seed as seed  # noqa: E402
from app.config import DB_PATH  # noqa: E402


@pytest.fixture()
def client():
    """每个用例一座空舱：删库重种，避免用例互相污染。"""
    if DB_PATH.exists():
        DB_PATH.unlink()
    seed.seed_if_empty()
    with TestClient(app_main.app) as c:
        yield c


@pytest.fixture()
def helper():
    return Helper()


class Helper:
    def pods(self, client):
        return {p["name"]: p for p in client.get("/api/舱体").json()}

    def align(self, client):
        data = client.get("/api/对读").json()
        return {p["name"]: p for p in data["舱体投影"]}, data

    def arm(self, client, value):
        return client.post("/api/舱规", json={"key": "运行态真源", "value": value}).json()

    def hand_edit(self, client, pod_id, state, **kw):
        body = {"run_state": state, **kw}
        r = client.post(f"/api/舱体/{pod_id}/运行态", json=body)
        return r

    def order(self, client, pod_id, action):
        return client.post("/api/启停单", json={"pod_id": pod_id, "action": action})

    def quota(self, client):
        return client.get("/api/配额").json()

    def orders(self, client):
        return client.get("/api/启停单").json()

    def orders_of(self, client, pod_id):
        return [o for o in self.orders(client) if o["pod_id"] == pod_id]
