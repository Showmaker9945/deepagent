const STREAM_EVENTS = ["classified", "clarification_needed", "research_started", "skeptic_started", "verdict_ready", "error"];
const TERMINAL_EVENTS = new Set(["verdict_ready", "error"]);
const EVENT_LABELS = {
  classified: "分类完成",
  clarification_needed: "需要补充",
  research_started: "开始查证",
  skeptic_started: "开始唱反调",
  verdict_ready: "结论已出",
  error: "运行出错",
};
const STATUS_LABELS = {
  queued: "已排队",
  running: "分析中",
  needs_clarification: "等你补一句",
  completed: "分析完成",
  failed: "分析失败",
};

const state = {
  runId: null,
  stream: null,
  seenEventIds: new Set(),
};

const $ = (selector) => document.querySelector(selector);

function collectPayload(form) {
  const formData = new FormData(form);
  return {
    question: (formData.get("question") || "").toString().trim(),
  };
}

function closeStream() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
}

function clearTimelinePlaceholder() {
  const timeline = $("#timeline");
  const placeholder = timeline.querySelector(".muted");
  if (placeholder && timeline.children.length === 1) {
    placeholder.remove();
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

  clearTimelinePlaceholder();

  const timeline = $("#timeline");
  const item = document.createElement("div");
  item.className = "timeline-item";
  item.innerHTML = `<strong>${EVENT_LABELS[eventType] || eventType}</strong><p>${formatEvent(eventType, payload)}</p>`;
  timeline.appendChild(item);
  timeline.scrollTop = timeline.scrollHeight;
}

function formatEvent(eventType, payload) {
  switch (eventType) {
    case "classified":
      $("#run-category").textContent = payload.category;
      return `路由到 ${payload.category}。${payload.reason}`;
    case "clarification_needed":
      return `先补一条关键信息：${payload.question}`;
    case "research_started":
      return "我在翻公开资料、用户上下文和你给的链接。";
    case "skeptic_started":
      return "反方队友上线，开始认真拆台。";
    case "verdict_ready":
      return "最终 verdict 已到达，准备接招。";
    case "error":
      return `出了点问题：${payload.message}`;
    default:
      return JSON.stringify(payload);
  }
}

function resetUi() {
  closeStream();
  state.seenEventIds = new Set();
  $("#timeline").innerHTML = '<p class="muted">时间线会在这里冒出来。</p>';
  $("#clarification-box").classList.add("hidden");
  $("#verdict-box").classList.add("hidden");
  $("#feedback-box").classList.add("hidden");
  $("#evidence-box").classList.add("hidden");
  $("#run-status").textContent = "分析中";
  $("#run-category").textContent = "未分类";
  $("#feedback-state").textContent = "";
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

function syncTimeline(events) {
  (events || []).forEach((event) => {
    addTimeline(event.event_type, event.payload, event.id);
  });
}

async function loadRun(runId) {
  const response = await fetch(`/api/runs/${runId}`);
  const data = await response.json();
  syncTimeline(data.events);
  const run = data.run;

  $("#run-status").textContent = STATUS_LABELS[run.status] || run.status;
  $("#run-category").textContent = run.category || "未分类";

  if (run.status === "needs_clarification" && run.clarification_question) {
    $("#clarification-box").classList.remove("hidden");
    $("#clarification-question").textContent = run.clarification_question;
  } else {
    $("#clarification-box").classList.add("hidden");
  }

  if (run.research_summary || run.skeptic_summary) {
    $("#evidence-box").classList.remove("hidden");
  } else {
    $("#evidence-box").classList.add("hidden");
  }

  if (run.research_summary) {
    $("#research-summary").textContent = run.research_summary.summary;
    renderList("#research-points", run.research_summary.supporting_evidence);
  }

  if (run.skeptic_summary) {
    $("#skeptic-summary").textContent = run.skeptic_summary.summary;
    renderList("#skeptic-points", run.skeptic_summary.risks);
  }

  if (run.verdict) {
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
  } else {
    $("#verdict-box").classList.add("hidden");
    $("#feedback-box").classList.add("hidden");
  }
}

function openStream(runId) {
  closeStream();
  const stream = new EventSource(`/api/runs/${runId}/stream`);
  state.stream = stream;

  STREAM_EVENTS.forEach((eventName) => {
    stream.addEventListener(eventName, async (event) => {
      const message = JSON.parse(event.data);
      const payload = message.payload;
      addTimeline(eventName, payload, event.lastEventId || message.id);

      if (eventName === "clarification_needed") {
        $("#clarification-box").classList.remove("hidden");
        $("#clarification-question").textContent = payload.question;
      }

      if (TERMINAL_EVENTS.has(eventName)) {
        closeStream();
      }

      if (eventName === "clarification_needed" || TERMINAL_EVENTS.has(eventName)) {
        await loadRun(runId);
      }
    });
  });

  stream.onerror = () => {
    if (stream.readyState === EventSource.CLOSED) {
      closeStream();
    }
  };
}

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  resetUi();

  const payload = collectPayload(event.currentTarget);
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  state.runId = data.run_id;
  openStream(state.runId);
  await loadRun(state.runId);
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
  addTimeline("classified", { category: "resumed", reason: "补充信息已收到，继续开工。" });
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
    ? "记住了。下次它会更早提醒你别踩同一个坑。"
    : "复盘没写进去，可能是这次 run 还没完全结束。";
});
