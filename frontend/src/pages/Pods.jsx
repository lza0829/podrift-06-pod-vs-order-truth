import React, { useEffect, useState } from "react";
import { api } from "../api";

const emptyDraft = { run_state: "运行中", note: "", expect_rev: "", 纠偏: false };

export default function Pods() {
  const [rows, setRows] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = () => api.pods().then(setRows);
  useEffect(() => { load(); }, []);

  const draft = (id) => drafts[id] || emptyDraft;
  const patch = (id, kv) => setDrafts((d) => ({ ...d, [id]: { ...draft(id), ...kv } }));

  const submit = (pod) => {
    const d = draft(pod.id);
    const body = {
      run_state: d.run_state,
      note: d.note,
      ...(d.expect_rev === "" ? {} : { expect_rev: Number(d.expect_rev) }),
      ...(d.纠偏 ? { 纠偏: true } : {}),
    };
    setBusy(pod.id);
    setMsg(null);
    api.editRunState(pod.id, body)
      .then((r) => {
        setMsg({ kind: "ok", text: `${pod.name}：${r.status} → ${r.后运行态}（列版本 ${r.列版本}，真源 ${r.真源}）` });
        load();
      })
      .catch((e) => {
        const det = e.detail || {};
        const hint = det.需纠偏
          ? `所选真源为启停单灯：需勾选「纠偏」才能改列；灯重放为 ${det.灯重放}，列为 ${det.列}`
          : det.冲突
            ? `列版本冲突：期望 ${det.期望版本}，当前 ${det.当前版本}（${det.当前列}）`
            : e.message;
        setMsg({ kind: "bad", text: `${pod.name}：${hint}` });
      })
      .finally(() => setBusy(null));
  };

  const arm = rows[0]?.真源 || "";
  return (
    <>
      <div className="hero">
        <h1>舱体</h1>
        <p>运行态格按选定真源重放；「列」原样留痕，「灯」只作附件。手改运行态当场落单并记事件痕。</p>
      </div>

      {arm && (
        <div className="banner">
          选定真源：<strong>{arm}</strong>
          {arm === "启停单已完成灯"
            ? " · 列只是缓存，手改列须勾选「纠偏」当场翻灯"
            : " · 列即权威，手改列直接改写读侧"}
        </div>
      )}

      {msg && <div className={`notice ${msg.kind}`}>{msg.text}</div>}

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>舱</th><th>镜像</th><th>拉取</th><th>运行（真源）</th><th>列</th>
              <th>列版本</th><th>灯</th><th>漂移</th><th>sidecar</th><th>配额</th><th>探针</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{r.image_name}:{r.image_tag}</td>
                <td>{r.pull_state}</td>
                <td><span className={`tag ${r.run_state === "运行中" ? "ok" : "warn"}`}>{r.run_state}</span></td>
                <td>{r.列}</td>
                <td>{r.列版本}</td>
                <td><span className={`tag ${lampClass(r.灯)}`}>{r.灯 || "—"}</span>{r.灯态 ? ` · ${r.灯态}` : ""}</td>
                <td>{r.漂移 ? <span className="tag bad">{r.漂移类型}</span> : <span className="muted">—</span>}</td>
                <td>{r.sidecar || "—"}</td>
                <td>{r.cpu_quota}c / {r.mem_quota_mb}MB</td>
                <td><span className={`tag ${r.probe_color === "绿" ? "ok" : "bad"}`}>{r.probe_color} · {r.fail_streak}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.map((r) => (
        <div className="panel" key={`edit-${r.id}`}>
          <div className="sub-head">
            手改运行态 · {r.name}
            <small>{r.漂移 && r.漂移说明 ? r.漂移说明 : "改列与落单同笔，" + (r.真源 === "启停单已完成灯" ? "先纠偏再刷缓存" : "写列即读侧生效")}</small>
          </div>
          <div className="form-row">
            <label>
              目标运行态
              <select value={draft(r.id).run_state} onChange={(e) => patch(r.id, { run_state: e.target.value })}>
                <option>运行中</option>
                <option>已停止</option>
              </select>
            </label>
            <label>
              期望列版本
              <input
                className="input"
                placeholder={`当前 ${r.列版本}（留空不校验）`}
                value={draft(r.id).expect_rev}
                onChange={(e) => patch(r.id, { expect_rev: e.target.value })}
              />
            </label>
            <label>
              备注
              <input className="input" value={draft(r.id).note} onChange={(e) => patch(r.id, { note: e.target.value })} />
            </label>
            {r.真源 === "启停单已完成灯" && (
              <label className="check">
                <input type="checkbox" checked={draft(r.id).纠偏} onChange={(e) => patch(r.id, { 纠偏: e.target.checked })} />
                纠偏
              </label>
            )}
            <button className="btn" disabled={busy === r.id} onClick={() => submit(r)}>
              {busy === r.id ? "落笔中…" : "手改运行态"}
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

function lampClass(lamp) {
  if (lamp === "已完成" || lamp === "纠偏") return "ok";
  if (lamp === "失败") return "bad";
  return "warn";
}
