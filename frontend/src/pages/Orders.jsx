import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function Orders() {
  const [pods, setPods] = useState([]);
  const [orders, setOrders] = useState([]);
  const [msg, setMsg] = useState(null);
  const load = () =>
    Promise.all([api.pods(), api.orders()]).then(([p, o]) => { setPods(p); setOrders(o); });
  useEffect(() => { load(); }, []);

  const act = (pod, action) => {
    setMsg(null);
    api.createOrder({ pod_id: pod.id, action })
      .then((r) => {
        setMsg({ kind: r.status === "已完成" ? "ok" : r.status === "失败" ? "bad" : "warn",
                 text: `${pod.name} ${action}：${r.status} · ${r.note}（${r.前运行态}→${r.后运行态}，真源 ${r.真源}）` });
        load();
      })
      .catch((e) => setMsg({ kind: "bad", text: e.message }));
  };

  const arm = pods[0]?.真源 || "";
  return (
    <>
      <div className="hero">
        <h1>启停单</h1>
        <p>运行态改写与启停推进同笔成败：单子要么真的改了运行态才点「已完成」，要么整笔失败/未生效。</p>
      </div>

      {arm && <div className="banner">选定真源：<strong>{arm}</strong> · 灯由运行态翻转重放得出，不另行谎点</div>}
      {msg && <div className={`notice ${msg.kind}`}>{msg.text}</div>}

      <div className="panel">
        <div className="row-actions">
          {pods.map((p) => (
            <span key={p.id} className="pod-actions">
              <strong>{p.name}</strong>{" "}
              <span className={`tag ${p.run_state === "运行中" ? "ok" : "warn"}`}>{p.run_state}</span>{" "}
              <button className="btn" onClick={() => act(p, "启动")}>启动</button>
              <button className="btn" onClick={() => act(p, "停止")}>停止</button>
            </span>
          ))}
        </div>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>舱</th><th>动作</th><th>状态</th><th>灯</th>
              <th>前→后运行态</th><th>列版本</th><th>说明</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>{o.pod_id}</td>
                <td>{o.action}</td>
                <td><span className={`tag ${o.status === "已完成" || o.status === "纠偏" ? "ok" : o.status === "失败" ? "bad" : "warn"}`}>{o.status}</span></td>
                <td><span className={`tag ${o.灯 === "已完成" || o.灯 === "纠偏" ? "ok" : o.灯 === "失败" ? "bad" : "warn"}`}>{o.灯}</span></td>
                <td>{o.prev_state || "—"} → {o.result_state || "—"}</td>
                <td>{o.state_rev ?? "—"}</td>
                <td>{o.note}</td>
                <td>{o.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
