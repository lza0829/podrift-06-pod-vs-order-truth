const j = async (url, opt) => {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opt,
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = body.detail;
    const text = typeof detail === "string"
      ? detail
      : detail?.说明 || body.错误 || `HTTP ${r.status}`;
    const err = new Error(text);
    err.status = r.status;
    err.detail = typeof detail === "object" ? detail : undefined;
    throw err;
  }
  return body;
};

export const api = {
  health: () => j("/api/健康"),
  images: () => j("/api/镜像"),
  advancePull: (id) => j(`/api/镜像/${id}/推进拉取`, { method: "POST" }),
  pods: () => j("/api/舱体"),
  orders: () => j("/api/启停单"),
  createOrder: (body) => j("/api/启停单", { method: "POST", body: JSON.stringify(body) }),
  editRunState: (podId, body) =>
    j(`/api/舱体/${podId}/运行态`, { method: "POST", body: JSON.stringify(body) }),
  probes: () => j("/api/探针"),
  setProbe: (podId, body) => j(`/api/探针/${podId}`, { method: "POST", body: JSON.stringify(body) }),
  quota: () => j("/api/配额"),
  policy: () => j("/api/重启策"),
  setPolicy: (body) => j("/api/重启策", { method: "POST", body: JSON.stringify(body) }),
  align: () => j("/api/对读"),
  settings: () => j("/api/舱规"),
  setSetting: (body) => j("/api/舱规", { method: "POST", body: JSON.stringify(body) }),
  setArm: (arm) => j("/api/舱规", { method: "POST", body: JSON.stringify({ key: "运行态真源", value: arm }) }),
  events: () => j("/api/事件"),
};
