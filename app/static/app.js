const STREAM_EVENTS = [
  "classified",
  "clarification_needed",
  "agent_started",
  "agent_token",
  "tool_started",
  "tool_finished",
  "source_captured",
  "verdict_ready",
  "cancel_requested",
  "cancelled",
  "timeout",
  "error",
];

const TERMINAL_EVENTS = new Set(["verdict_ready", "cancelled", "timeout", "error"]);
const TIMELINE_EVENTS = new Set([
  "classified",
  "clarification_needed",
  "agent_started",
  "tool_started",
  "tool_finished",
  "verdict_ready",
  "cancel_requested",
  "cancelled",
  "timeout",
  "error",
]);

const EVENT_LABELS = {
  classified: "分类完成",
  clarification_needed: "需要补充",
  agent_started: "开始分析",
  tool_started: "工具启动",
  tool_finished: "工具返回",
  verdict_ready: "结论生成",
  cancel_requested: "收到停止请求",
  cancelled: "分析已停止",
  timeout: "分析超时",
  error: "运行出错",
};

const STATUS_LABELS = {
  queued: "已排队",
  running: "分析中",
  needs_clarification: "等你补一句",
  completed: "分析完成",
  failed: "分析失败",
  cancelled: "已停止",
  timed_out: "超时收手",
};

const CATEGORY_LABELS = {
  spending: "消费判断",
  travel: "出行活动",
  work_learning: "工作学习",
  social: "社交关系",
  unsupported: "高风险问题",
};

const MAX_IMAGE_COUNT = 3;

const state = {
  runId: null,
  stream: null,
  seenEventIds: new Set(),
  seenSourceKeys: new Set(),
  draftText: "",
};

const $ = (selector) => document.querySelector(selector);

function collectPayload(form, imageIds = []) {
  const formData = new FormData(form);
  return {
    question: (formData.get("question") || "").toString().trim(),
    image_ids: imageIds,
  };
}

function closeStream() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
}

function canCancelRun(run) {
  return ["queued", "running", "needs_clarification"].includes(run.status) && !run.cancel_requested;
}

function setStatus(status) {
  $("#run-status").textContent = STATUS_LABELS[status] || status || "待命中";
}

function setCategory(category) {
  $("#run-category").textContent = CATEGORY_LABELS[category] || "未分类";
}

function setCancelVisibility(visible) {
  $("#cancel-button").classList.toggle("hidden", !visible);
}

function setFormState(message = "", isError = false) {
  const target = $("#form-state");
  target.textContent = message;
  target.classList.toggle("error-text", Boolean(isError && message));
}

function clearTimelinePlaceholder() {
  const timeline = $("#timeline");
  const placeholder = timeline.querySelector(".muted");
  if (placeholder && timeline.children.length === 1) {
    placeholder.remove();
  }
}

function formatEvent(eventType, payload) {
  switch (eventType) {
    case "classified":
      setCategory(payload.category);
      return `归到 ${CATEGORY_LABELS[payload.category] || payload.category}：${payload.reason}`;
    case "clarification_needed":
      return `还差一条关键信息：${payload.question}`;
    case "agent_started":
      return payload.message || "Deep Agent 已经接手。";
    case "tool_started":
      return payload.summary || `开始调用 ${payload.tool_name}`;
    case "tool_finished":
      return payload.summary || `${payload.tool_name} 已返回`;
    case "verdict_ready":
      return "最终 verdict 已经出来了。";
    case "cancel_requested":
      return payload.message || "已经在收手了。";
    case "cancelled":
      return payload.message || "这轮分析被停下来了。";
    case "timeout":
      return payload.message || "这轮分析拖太久，系统替你踩了刹车。";
    case "error":
      return `出了点问题：${payload.message || "未知错误"}`;
    default:
      return JSON.stringify(payload);
  }
}

function addTimeline(eventType, payload, eventId = null) {
  const hasEventId = eventId !== null && eventId !== undefined && eventId !== "";
  const numericId = hasEventId ? Number(eventId) : null;
  if (Number.isInteger(numericId) && state.seenEventIds.has(numericId)) {
    return;
  }
  if (Number.isInteger(numericId)) {
    state.seenEventIds.add(numericId);
  }
  if (!TIMELINE_EVENTS.has(eventType)) {
    return;
  }

  clearTimelinePlaceholder();

  const timeline = $("#timeline");
  const item = document.createElement("div");
  item.className = "timeline-item";
  item.innerHTML = `<strong>${EVENT_LABELS[eventType] || eventType}</strong><p>${formatEvent(eventType, payload)}</p>`;
  timeline.appendChild(item);
  timeline.scrollTop = timeline.scrollHeight;
}

function appendDraft(text) {
  if (!text) return;
  state.draftText += text;
  const draft = $("#agent-draft");
  draft.classList.remove("muted");
  draft.textContent = state.draftText;
  draft.scrollTop = draft.scrollHeight;
}

function resetDraft() {
  state.draftText = "";
  const draft = $("#agent-draft");
  draft.classList.add("muted");
  draft.textContent = "Deep Agent 一开口，这里就会开始冒字。";
}

function renderList(selector, items) {
  const target = $(selector);
  target.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  });
}

function sourceKey(source) {
  return `${source.source_id || source.id || ""}|${source.source_type || ""}|${source.url || ""}|${source.title || ""}`;
}

function createSourceCard(source) {
  const card = document.createElement("article");
  card.className = "source-card";

  const head = document.createElement("div");
  head.className = "source-head";

  const typeTag = document.createElement("span");
  typeTag.className = "tag ghost";
  typeTag.textContent =
    {
      search_result: "搜索结果",
      webpage: "链接正文",
      location: "地点数据",
      weather: "天气数据",
      tool_note: "工具备注",
    }[source.source_type] || source.source_type || "依据";

  const title = document.createElement(source.url ? "a" : "strong");
  if (source.url) {
    title.href = source.url;
    title.target = "_blank";
    title.rel = "noreferrer";
  }
  title.textContent = source.title || source.url || "未命名来源";

  head.appendChild(typeTag);
  head.appendChild(title);
  card.appendChild(head);

  if (source.snippet) {
    const snippet = document.createElement("p");
    snippet.className = "muted";
    snippet.textContent = source.snippet;
    card.appendChild(snippet);
  }

  const meta = source.source_meta || {};
  const metaParts = [];
  if (meta.query) metaParts.push(`查询：${meta.query}`);
  if (meta.start_date && meta.end_date) metaParts.push(`日期：${meta.start_date} ~ ${meta.end_date}`);
  if (meta.latitude && meta.longitude) metaParts.push(`坐标：${meta.latitude}, ${meta.longitude}`);
  if (meta.image_count) metaParts.push(`图片：${meta.image_count} 张`);
  if (metaParts.length) {
    const metaLine = document.createElement("p");
    metaLine.className = "muted tiny";
    metaLine.textContent = metaParts.join(" · ");
    card.appendChild(metaLine);
  }

  return card;
}

function appendSource(source) {
  const key = sourceKey(source);
  if (state.seenSourceKeys.has(key)) return;
  state.seenSourceKeys.add(key);

  $("#sources-box").classList.remove("hidden");
  $("#sources-list").appendChild(createSourceCard(source));
}

function renderSources(sources) {
  const list = $("#sources-list");
  list.innerHTML = "";
  state.seenSourceKeys = new Set();
  if (!sources || !sources.length) {
    $("#sources-box").classList.add("hidden");
    return;
  }
  $("#sources-box").classList.remove("hidden");
  sources.forEach((source) => appendSource(source));
}

function applyEvent(eventType, payload, eventId = null) {
  if (eventType === "agent_token") {
    const numericId = eventId !== null && eventId !== undefined && eventId !== "" ? Number(eventId) : null;
    if (Number.isInteger(numericId) && state.seenEventIds.has(numericId)) return;
    if (Number.isInteger(numericId)) state.seenEventIds.add(numericId);
    appendDraft(payload.text || "");
    return;
  }

  if (eventType === "source_captured") {
    const numericId = eventId !== null && eventId !== undefined && eventId !== "" ? Number(eventId) : null;
    if (Number.isInteger(numericId) && state.seenEventIds.has(numericId)) return;
    if (Number.isInteger(numericId)) state.seenEventIds.add(numericId);
    appendSource(payload);
    return;
  }

  addTimeline(eventType, payload, eventId);

  if (eventType === "clarification_needed") {
    $("#clarification-box").classList.remove("hidden");
    $("#clarification-question").textContent = payload.question || "";
  }

  if (TERMINAL_EVENTS.has(eventType)) {
    setCancelVisibility(false);
  }
}

function resetUi() {
  closeStream();
  state.seenEventIds = new Set();
  state.seenSourceKeys = new Set();
  $("#timeline").innerHTML = '<p class="muted">时间线会在这里出现。</p>';
  $("#clarification-box").classList.add("hidden");
  $("#verdict-box").classList.add("hidden");
  $("#feedback-box").classList.add("hidden");
  $("#sources-box").classList.add("hidden");
  $("#sources-list").innerHTML = "";
  $("#feedback-state").textContent = "";
  setStatus("running");
  setCategory(null);
  setCancelVisibility(false);
  resetDraft();
}

function syncTimeline(events) {
  (events || []).forEach((event) => {
    applyEvent(event.event_type, event.payload, event.id);
  });
}

function renderVerdict(run) {
  if (!run.verdict) {
    $("#verdict-box").classList.add("hidden");
    $("#feedback-box").classList.add("hidden");
    return;
  }

  const verdict = run.verdict;
  $("#verdict-box").classList.remove("hidden");
  $("#feedback-box").classList.remove("hidden");
  $("#verdict-label").textContent = verdict.verdict;
  $("#verdict-confidence").textContent = `把握度 ${Math.round(verdict.confidence * 100)}%`;
  $("#verdict-punchline").textContent = verdict.punchline || "";
  $("#best-alternative").textContent = verdict.best_alternative;
  $("#next-step").textContent = verdict.recommended_next_step;
  $("#follow-up").textContent = verdict.follow_up_question || "";
  renderList("#why-yes", verdict.why_yes);
  renderList("#why-no", verdict.why_no);
  renderList("#top-risks", verdict.top_risks);
}

function renderSelectedImages(files) {
  const selected = Array.from(files || []).slice(0, MAX_IMAGE_COUNT);
  const box = $("#image-selection");
  const list = $("#image-selection-list");
  list.innerHTML = "";
  if (!selected.length) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  selected.forEach((file) => {
    const li = document.createElement("li");
    li.textContent = `${file.name} (${Math.max(1, Math.round(file.size / 1024))} KB)`;
    list.appendChild(li);
  });
}

async function uploadImages(files) {
  const chosen = Array.from(files || []).slice(0, MAX_IMAGE_COUNT);
  const uploadedIds = [];

  for (const file of chosen) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/uploads", {
      method: "POST",
      body,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `图片上传失败：${file.name}`);
    }
    uploadedIds.push(data.id);
  }

  return uploadedIds;
}

async function loadRun(runId) {
  const response = await fetch(`/api/runs/${runId}`);
  const data = await response.json();
  syncTimeline(data.events);

  const run = data.run;
  setStatus(run.status);
  setCategory(run.category);
  setCancelVisibility(canCancelRun(run));

  if (run.status === "needs_clarification" && run.clarification_question) {
    $("#clarification-box").classList.remove("hidden");
    $("#clarification-question").textContent = run.clarification_question;
  } else {
    $("#clarification-box").classList.add("hidden");
  }

  renderSources(data.sources || []);
  renderVerdict(run);
}

function openStream(runId) {
  closeStream();
  const stream = new EventSource(`/api/runs/${runId}/stream`);
  state.stream = stream;

  STREAM_EVENTS.forEach((eventName) => {
    stream.addEventListener(eventName, async (event) => {
      const message = JSON.parse(event.data);
      applyEvent(eventName, message.payload, event.lastEventId || message.id);

      if (eventName === "clarification_needed" || TERMINAL_EVENTS.has(eventName)) {
        await loadRun(runId);
      }

      if (TERMINAL_EVENTS.has(eventName)) {
        closeStream();
      }
    });
  });

  stream.onerror = () => {
    if (stream.readyState === EventSource.CLOSED) {
      closeStream();
    }
  };
}

$("#image-input").addEventListener("change", (event) => {
  renderSelectedImages(event.currentTarget.files);
});

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setFormState("");
  resetUi();

  const form = event.currentTarget;
  const imageFiles = $("#image-input").files;

  try {
    if (!collectPayload(form).question) {
      throw new Error("先把问题写下来，我才能开始判断。");
    }

    let imageIds = [];
    if (imageFiles && imageFiles.length) {
      setFormState("正在上传图片...");
      imageIds = await uploadImages(imageFiles);
    }

    setFormState("正在发起这轮判断...");
    const payload = collectPayload(form, imageIds);
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "创建 run 失败。");
    }

    state.runId = data.run_id;
    setCancelVisibility(true);
    setFormState("");
    openStream(state.runId);
    await loadRun(state.runId);
  } catch (error) {
    closeStream();
    setCancelVisibility(false);
    setFormState(error.message || "提交失败，请稍后再试。", true);
  }
});

$("#clarification-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.runId) return;
  const form = event.currentTarget;
  const answer = new FormData(form).get("answer");
  await fetch(`/api/runs/${state.runId}/clarifications`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  form.reset();
  $("#clarification-box").classList.add("hidden");
  resetDraft();
  openStream(state.runId);
  await loadRun(state.runId);
});

$("#feedback-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.runId) return;
  const formData = new FormData(event.currentTarget);
  const payload = {
    actual_action: formData.get("actual_action"),
    satisfaction_score: Number(formData.get("satisfaction_score")),
    regret_score: Number(formData.get("regret_score")),
    note: formData.get("note") || null,
  };
  const response = await fetch(`/api/runs/${state.runId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("#feedback-state").textContent = response.ok
    ? "记住了。下次它会更早提醒你别在同一个坑里二次团建。"
    : "这次复盘没写进去，可能 run 还没完全落稳。";
});

$("#cancel-button").addEventListener("click", async () => {
  if (!state.runId) return;
  const response = await fetch(`/api/runs/${state.runId}/cancel`, { method: "POST" });
  setCancelVisibility(false);
  if (response.ok) {
    await loadRun(state.runId);
  }
});
