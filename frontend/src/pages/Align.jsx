import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function Align() {
  const [data, setData] = useState(null);
  const load = () => api.align().then(setData);
  useEffect(() => { load(); }, []);

  const switchArm = (code) => api.setArm(code).then(load);

  if (!data) return null;
  const rows = data["舱体投影"];
  return (
    <>
      <div className="hero">
        <h1>对读屏</h1>
        <p>运行格只听所选真源；灯、列、事件痕在同一行互证，两臂裁决可在同一夹具下切换对照。</p>
      </div>

      <div className="panel">
        <div className="sub-head">当前真源：<strong>{data["真源"]}</strong></div>
        <div className="row-actions">
          {Object.entries(data["可选臂"] || {}).map(([code, label]) => (
            <button
              key={code}
              className={`btn ${code === data["真源代码"] ? "btn-active" : ""}`}
              onClick={() => switchArm(code)}
            >
              {code === "列" ? "臂A" : "臂B"} · {label}
            </button>
          ))}
          <button className="btn" onClick={load}>刷新</button>
        </div>
        <div className="muted small">切臂落事件痕；读侧下一次取数即按新臂重放，同一夹具能看出「列停灯成」跟列与跟灯的分歧。</div>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>舱</th><th>运行（真源）</th><th>依据</th><th>列</th><th>列版本</th>
              <th>灯</th><th>灯态</th><th>最近启停</th><th>漂移</th><th>探针</th><th>镜像</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.漂移 ? "row-drift" : ""}>
                <td>{r.name}</td>
                <td><span className={`tag ${r.运行 === "运行中" ? "ok" : "warn"}`}>{r.运行}</span></td>
                <td className="muted">{r.依据}</td>
                <td>{r.列}</td>
                <td>{r.列版本}</td>
                <td><span className={`tag ${r.灯 === "已完成" || r.灯 === "纠偏" ? "ok" : r.灯 === "失败" ? "bad" : "warn"}`}>{r.灯 || "—"}</span></td>
                <td>{r.灯态 || "—"}</td>
                <td>{r.last_order_status || "—"} {r.last_order_note || ""}</td>
                <td>{r.漂移 ? <span className="tag bad">{r.漂移类型}</span> : <span className="muted">—</span>}</td>
                <td>{r.probe_color} · {r.fail_streak}</td>
                <td>{r.pull_state}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.some((r) => r.漂移) && (
        <div className="notice warn">
          {rows.filter((r) => r.漂移).map((r) => `${r.name}：${r.漂移说明}`).join("；")}
        </div>
      )}
    </>
  );
}
