import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function Rules() {
  const [settings, setSettings] = useState([]);
  const [events, setEvents] = useState([]);
  const load = () => Promise.all([api.settings(), api.events()]).then(([s, e]) => { setSettings(s); setEvents(e); });
  useEffect(() => { load(); }, []);

  const truth = settings.find((s) => s.key === "运行态真源");
  return (
    <>
      <div className="hero">
        <h1>舱规</h1>
        <p>全局口径与事件痕。事件旁读只作附件：运行态真源由「运行态真源」一栏选定，读侧按它重放。</p>
      </div>

      <div className="panel">
        <table>
          <thead><tr><th>键</th><th>值</th></tr></thead>
          <tbody>
            {settings.map((s) => (
              <tr key={s.key}>
                <td>{s.key}</td>
                <td>{s.key === "运行态真源" ? <span className="tag warn">{s.value}</span> : s.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row-actions">
          <button className="btn" onClick={() => api.setArm("列").then(load)}>选定臂A · 运行态列</button>
          <button className="btn" onClick={() => api.setArm("灯").then(load)}>选定臂B · 启停单已完成灯</button>
        </div>
        <div className="muted small">
          当前选定：{truth ? truth.value : "运行态列"}（在「对读屏」可直接切换对照两臂裁决）
        </div>
      </div>

      <div className="panel">
        <table>
          <thead><tr><th>事件</th><th>引用</th><th>详情</th><th>时间</th></tr></thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}><td>{e.kind}</td><td>{e.ref}</td><td>{e.detail}</td><td>{e.at}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
