/* TriageDesk Interactive Workspace Controller */

const TOKEN_KEY = "triagedesk_jwt";
let currentUser = null;
let activeView = "dashboard";
let selectedTicketId = null;
let selectedBulkIds = new Set();
let staffDirectory = [];
let groupsCache = [];

const PRIORITY_BADGES = {
  URGENT: "text-bg-danger",
  HIGH: "text-bg-warning",
  MEDIUM: "text-bg-info",
  LOW: "text-bg-secondary",
};

const PRIORITY_COLORS = {
  URGENT: "#ef4444",
  HIGH: "#f97316",
  MEDIUM: "#06b6d4",
  LOW: "#64748b",
};

const STATUS_BADGES = {
  OPEN: "text-bg-primary",
  IN_PROGRESS: "text-bg-warning",
  WAITING_CUSTOMER: "text-bg-info",
  RESOLVED: "text-bg-success",
  CLOSED: "text-bg-secondary",
};

const TRANSITION_OPTIONS = {
  OPEN: ["OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED", "CLOSED"],
  IN_PROGRESS: ["IN_PROGRESS", "OPEN", "WAITING_CUSTOMER", "RESOLVED", "CLOSED"],
  WAITING_CUSTOMER: ["WAITING_CUSTOMER", "IN_PROGRESS", "RESOLVED", "CLOSED"],
  RESOLVED: ["RESOLVED", "CLOSED", "IN_PROGRESS"],
  CLOSED: ["CLOSED", "IN_PROGRESS"],
};

/* ---------- Theme Persistence (dark-mode-toggle compliant) ---------- */
function syncBootstrapTheme() {
  const meta = document.querySelector('meta[name="color-scheme"]');
  const content = meta?.content || "light dark";
  const resolvedDark =
    content === "dark" ||
    (content === "light dark" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-bs-theme", resolvedDark ? "dark" : "light");
}

function toggleColorScheme() {
  const meta = document.querySelector('meta[name="color-scheme"]');
  const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  let stored = null;
  try {
    stored = localStorage.getItem("color-scheme");
  } catch {}
  const currentlyDark = stored ? stored === "dark" : sysDark;
  const target = currentlyDark ? "light" : "dark";
  const systemLabel = sysDark ? "dark" : "light";

  try {
    if (target === systemLabel) localStorage.removeItem("color-scheme");
    else localStorage.setItem("color-scheme", target);
  } catch {}
  if (meta) meta.content = target === systemLabel ? "light dark" : target;
  syncBootstrapTheme();
}

window.addEventListener("storage", (e) => {
  if (e.key === "color-scheme") {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.content = e.newValue ?? "light dark";
    syncBootstrapTheme();
  }
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", syncBootstrapTheme);
syncBootstrapTheme();

/* ---------- Accessible Form Error Announcement ---------- */
const linkError = (el, shown) => {
  const errorId = el.dataset.error;
  if (!errorId) return;
  const ids = (el.getAttribute("aria-describedby") || "")
    .split(/\s+/)
    .filter((id) => id && id !== errorId);
  if (shown) ids.push(errorId);
  if (ids.length) el.setAttribute("aria-describedby", ids.join(" "));
  else el.removeAttribute("aria-describedby");
};

const announcer = document.createElement("div");
announcer.setAttribute("aria-live", "polite");
announcer.classList.add("visually-hidden");
document.body.append(announcer);
let announceTimer;
const announced = new WeakSet();

const syncAria = (el, shouldAnnounce = false) => {
  if (!el?.matches?.("input, select, textarea")) return;
  const supportsUserInvalid = CSS.supports("selector(:user-invalid)");
  const invalid = supportsUserInvalid ? el.matches(":user-invalid") : el.classList.contains("user-invalid-fallback");
  if (invalid) {
    if (shouldAnnounce && !announced.has(el)) {
      const err = document.getElementById(el.dataset.error);
      if (err) {
        clearTimeout(announceTimer);
        announceTimer = setTimeout(() => {
          announcer.textContent = err.textContent.trim();
        }, 400);
      }
      announced.add(el);
    }
    el.setAttribute("aria-invalid", "true");
    linkError(el, true);
  } else {
    el.setAttribute("aria-invalid", "false");
    linkError(el, false);
    announced.delete(el);
  }
};

document.querySelectorAll("input, select, textarea").forEach((el) => syncAria(el));
document.addEventListener("blur", (e) => syncAria(e.target, true), true);
document.addEventListener("input", (e) => {
  if (e.target?.hasAttribute("aria-invalid")) syncAria(e.target);
});
document.addEventListener("invalid", (e) => {
  e.target?.classList?.add("user-invalid-fallback");
  announced.add(e.target);
  syncAria(e.target);
}, true);

/* ---------- Accessible Tablist Switching (tabs compliant) ---------- */
const tabButtons = [...document.querySelectorAll('[role="tab"]')];
const tabPanels = [...document.querySelectorAll('[role="tabpanel"]')];

function activateTab(tab) {
  tabButtons.forEach((btn) => {
    const selected = btn === tab;
    btn.setAttribute("aria-selected", String(selected));
    btn.toggleAttribute("focusgroupstart", selected);
  });
  tabPanels.forEach((panel) => {
    const match = panel.getAttribute("aria-labelledby") === tab.id;
    if (match) {
      panel.removeAttribute("hidden");
      panel.setAttribute("tabindex", "0");
    } else {
      panel.setAttribute("hidden", "until-found");
      panel.removeAttribute("tabindex");
    }
  });
  tab.scrollIntoView({ block: "nearest", inline: "nearest", container: "nearest" });
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn));
  btn.addEventListener("keydown", (e) => {
    const idx = tabButtons.indexOf(btn);
    if (e.key === "ArrowRight") {
      const next = tabButtons[(idx + 1) % tabButtons.length];
      next.focus();
      activateTab(next);
    } else if (e.key === "ArrowLeft") {
      const prev = tabButtons[(idx - 1 + tabButtons.length) % tabButtons.length];
      prev.focus();
      activateTab(prev);
    }
  });
});

tabPanels.forEach((panel) => {
  panel.addEventListener("beforematch", () => {
    const tab = document.getElementById(panel.getAttribute("aria-labelledby"));
    if (tab) activateTab(tab);
  });
});

/* ---------- Helpers & API Client ---------- */
function showAlert(message, type = "danger") {
  const boxId = currentUser ? "workspace-alert" : "auth-alert";
  const box = document.getElementById(boxId);
  if (!message) {
    box.className = "alert d-none mb-3";
    box.textContent = "";
    return;
  }
  box.className = `alert alert-${type} mb-3`;
  box.textContent = message;
  if (type === "success") {
    setTimeout(() => {
      if (box.textContent === message) {
        box.className = "alert d-none mb-3";
        box.textContent = "";
      }
    }, 3500);
  }
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401 && path !== "/api/v1/auth/login") {
    localStorage.removeItem(TOKEN_KEY);
    currentUser = null;
    renderShell();
    throw new Error("Session expired. Please sign in again.");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.detail || `Request failed (${res.status})`);
  }
  return data;
}

function makeBadge(text, cls) {
  const span = document.createElement("span");
  span.className = `badge ${cls}`;
  span.textContent = text;
  return span;
}

function formatDuration(mins) {
  if (mins === null || mins === undefined) return "--";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function formatUtc(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function initials(name) {
  return (name || "U")
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() || "")
    .join("");
}

/* ---------- Navigation & Shell ---------- */
function renderShell() {
  const authShell = document.getElementById("auth-shell");
  const appShell = document.getElementById("app-shell");
  if (!currentUser) {
    authShell.hidden = false;
    appShell.hidden = true;
    return;
  }
  authShell.hidden = true;
  appShell.hidden = false;

  document.getElementById("topbar-avatar").textContent = initials(currentUser.full_name);
  document.getElementById("topbar-user-name").textContent = currentUser.full_name;
  document.getElementById("topbar-user-role").textContent = currentUser.role;

  const isStaff = currentUser.role === "AGENT" || currentUser.role === "ADMIN";
  const isAdmin = currentUser.role === "ADMIN";
  document.getElementById("sidebar-admin-group").classList.toggle("d-none", !isStaff);
  document.getElementById("nav-users-btn").classList.toggle("d-none", !isAdmin);
  document.getElementById("assigned-me-wrap").classList.toggle("d-none", !isStaff);
  document.getElementById("select-all-tickets").classList.toggle("d-none", !isStaff);
  document.getElementById("create-group-card").classList.toggle("d-none", !isAdmin);
  document.getElementById("queue-scope-hint").textContent = isStaff
    ? "Staff view: all workspace tickets sorted by priority and SLA"
    : "Customer portal: showing your submitted tickets";
}

function showView(viewName) {
  activeView = viewName;
  ["dashboard", "tickets", "detail", "users", "groups", "api-keys", "sla"].forEach((v) => {
    document.getElementById(`view-${v}`).hidden = v !== viewName;
  });
  document.querySelectorAll(".td-nav-item").forEach((btn) => {
    const match = btn.dataset.view === (viewName === "detail" ? "tickets" : viewName);
    btn.classList.toggle("active", match);
  });
  document.getElementById("topbar-context").textContent = viewName.toUpperCase();
  document.querySelector(".td-sidebar")?.classList.remove("open");
}

async function navigateTo(viewName) {
  showView(viewName);
  showAlert("");
  try {
    if (viewName === "dashboard") await loadDashboard();
    else if (viewName === "tickets") await loadTicketsView();
    else if (viewName === "users") await loadUsersView();
    else if (viewName === "groups") await loadGroupsView();
    else if (viewName === "api-keys") await loadApiKeysView();
    else if (viewName === "sla") await loadSlaView();
  } catch (err) {
    showAlert(err.message);
  }
}

/* ---------- Dashboard ---------- */
async function loadDashboard() {
  const data = await apiFetch("/api/v1/dashboard");
  const kpiRow = document.getElementById("dash-kpis");
  kpiRow.replaceChildren();

  const cards = [
    ["Open", data.open_count, "td-kpi-open", "bi-ticket"],
    ["In Progress", data.in_progress_count, "td-kpi-progress", "bi-search"],
    ["Waiting Customer", data.waiting_customer_count, "td-kpi-waiting", "bi-hourglass-split"],
    ["Resolved / Closed", data.resolved_or_closed_count, "td-kpi-resolved", "bi-check-circle"],
  ];
  for (const [label, count, cls, icon] of cards) {
    const col = document.createElement("div");
    col.className = "col-6 col-xl-3";
    const card = document.createElement("div");
    card.className = `card td-card ${cls}`;
    const body = document.createElement("div");
    body.className = "card-body d-flex justify-content-between align-items-start";
    const left = document.createElement("div");
    const num = document.createElement("div");
    num.className = "fs-2 fw-bold";
    num.textContent = String(count);
    const lbl = document.createElement("div");
    lbl.className = "small td-muted";
    lbl.textContent = label;
    left.append(num, lbl);
    const ic = document.createElement("i");
    ic.className = `bi ${icon} fs-4 td-muted`;
    body.append(left, ic);
    card.append(body);
    col.append(card);
    kpiRow.append(col);
  }

  document.getElementById("dash-mtta").textContent = formatDuration(data.mtta_minutes);
  document.getElementById("dash-mttr").textContent = formatDuration(data.mttr_minutes);

  const bar = document.getElementById("dash-prio-bar");
  const legend = document.getElementById("dash-prio-legend");
  bar.replaceChildren();
  legend.replaceChildren();

  for (const s of data.priority_distribution) {
    if (s.percent > 0) {
      const seg = document.createElement("div");
      seg.className = "progress-bar";
      seg.style.width = `${s.percent}%`;
      seg.style.backgroundColor = PRIORITY_COLORS[s.priority];
      seg.setAttribute("aria-label", `${s.priority} ${s.percent}%`);
      bar.append(seg);
    }
    const item = document.createElement("span");
    item.className = "d-inline-flex align-items-center gap-1";
    const dot = document.createElement("span");
    dot.style.cssText = `width:10px;height:10px;border-radius:2px;background:${PRIORITY_COLORS[s.priority]};display:inline-block`;
    const txt = document.createElement("span");
    txt.textContent = `${s.priority}: ${s.count} (${s.percent}%)`;
    item.append(dot, txt);
    legend.append(item);
  }

  const feed = document.getElementById("dash-recent-activity");
  feed.replaceChildren();
  if (!data.recent_activity.length) {
    const li = document.createElement("li");
    li.className = "small td-muted";
    li.textContent = "No ticket activity recorded yet.";
    feed.append(li);
    return;
  }
  for (const ev of data.recent_activity) {
    const li = document.createElement("li");
    li.className = "d-flex justify-content-between align-items-center small border-bottom pb-2";
    const left = document.createElement("div");
    const actor = document.createElement("span");
    actor.className = "fw-semibold";
    actor.textContent = `${ev.actor_name} `;
    const act = document.createElement("span");
    act.className = "td-muted";
    const delta = ev.old_value ? ` (${ev.field_name}: ${ev.old_value} -> ${ev.new_value})` : "";
    act.textContent = `${ev.event_type.toLowerCase()} on `;
    const link = document.createElement("button");
    link.type = "button";
    link.className = "btn btn-link btn-sm p-0 fw-semibold align-baseline text-decoration-none";
    link.textContent = ev.ticket_key;
    link.addEventListener("click", () => openTicketDetail(ev.ticket_id));
    const tail = document.createElement("span");
    tail.className = "td-muted";
    tail.textContent = delta;
    left.append(actor, act, link, tail);

    const ts = document.createElement("span");
    ts.className = "td-muted ms-2 text-nowrap";
    ts.textContent = formatUtc(ev.created_at);
    li.append(left, ts);
    feed.append(li);
  }
}

/* ---------- Reference Lookups ---------- */
async function refreshLookups() {
  const isStaff = currentUser.role === "AGENT" || currentUser.role === "ADMIN";
  const reqs = [apiFetch("/api/v1/groups").then((d) => { groupsCache = d; })];
  if (isStaff) {
    reqs.push(apiFetch("/api/v1/users/agents").then((d) => { staffDirectory = d; }));
  }
  await Promise.all(reqs);

  const populateGroupSelect = (id, blankLabel) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.replaceChildren();
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = blankLabel;
    sel.append(blank);
    for (const g of groupsCache) {
      const opt = document.createElement("option");
      opt.value = String(g.id);
      opt.textContent = g.name;
      if (String(g.id) === prev) opt.selected = true;
      sel.append(opt);
    }
  };
  populateGroupSelect("ticket-group", "Auto / Unassigned");
  populateGroupSelect("filter-group", "All Groups");

  const bulkAssign = document.getElementById("bulk-assignee");
  bulkAssign.replaceChildren();
  const baseOpt = document.createElement("option");
  baseOpt.value = "";
  baseOpt.textContent = "Assign user...";
  bulkAssign.append(baseOpt);
  for (const st of staffDirectory) {
    const opt = document.createElement("option");
    opt.value = String(st.id);
    opt.textContent = st.full_name;
    bulkAssign.append(opt);
  }
}

/* ---------- Tickets Queue & Bulk ---------- */
function syncBulkBar() {
  const isStaff = currentUser?.role === "AGENT" || currentUser?.role === "ADMIN";
  const bar = document.getElementById("bulk-bar");
  const show = isStaff && selectedBulkIds.size > 0;
  bar.classList.toggle("d-none", !show);
  document.getElementById("bulk-count-label").textContent = `${selectedBulkIds.size} selected`;
}

async function loadTicketsView() {
  await refreshLookups();
  const params = new URLSearchParams();
  const q = document.getElementById("filter-search").value.trim();
  const st = document.getElementById("filter-status").value;
  const pr = document.getElementById("filter-priority").value;
  const gr = document.getElementById("filter-group").value;
  const mine = document.getElementById("filter-assigned-me").checked;
  if (q) params.set("q", q);
  if (st) params.set("status", st);
  if (pr) params.set("priority", pr);
  if (gr) params.set("group_id", gr);
  if (mine) params.set("assigned_to_me", "true");

  const tickets = await apiFetch(`/api/v1/tickets?${params.toString()}`);
  const isStaff = currentUser.role === "AGENT" || currentUser.role === "ADMIN";
  const tbody = document.getElementById("tickets-tbody");
  tbody.replaceChildren();

  if (!tickets.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "text-center td-muted py-4";
    td.textContent = "No tickets match the current filters.";
    tr.append(td);
    tbody.append(tr);
    syncBulkBar();
    return;
  }

  for (const t of tickets) {
    const tr = document.createElement("tr");
    const tdChk = document.createElement("td");
    tdChk.className = "td-col-check";
    tdChk.addEventListener("click", (ev) => ev.stopPropagation());
    if (isStaff) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "form-check-input ticket-bulk-cb";
      cb.checked = selectedBulkIds.has(t.id);
      cb.setAttribute("aria-label", `Select ${t.ticket_key}`);
      cb.addEventListener("change", () => {
        if (cb.checked) selectedBulkIds.add(t.id);
        else selectedBulkIds.delete(t.id);
        syncBulkBar();
      });
      tdChk.append(cb);
    }

    const th = document.createElement("th");
    th.scope = "row";
    const keyLine = document.createElement("div");
    keyLine.className = "small td-muted font-monospace";
    keyLine.textContent = `${t.ticket_key} · ${t.created_by_name}`;
    const titleLine = document.createElement("div");
    titleLine.className = "fw-semibold";
    titleLine.textContent = t.title;
    th.append(keyLine, titleLine);

    const tdPrio = document.createElement("td");
    tdPrio.append(makeBadge(t.priority, PRIORITY_BADGES[t.priority] || "text-bg-secondary"));

    const tdStatus = document.createElement("td");
    tdStatus.append(makeBadge(t.status, STATUS_BADGES[t.status] || "text-bg-secondary"));

    const tdGroup = document.createElement("td");
    tdGroup.className = "small";
    tdGroup.textContent = t.group_name || "Unassigned";

    const tdAssign = document.createElement("td");
    tdAssign.className = "small";
    tdAssign.textContent = t.assigned_to_name || "Unassigned";

    const tdSla = document.createElement("td");
    tdSla.append(
      t.sla_breached
        ? makeBadge("BREACHED", "text-bg-danger")
        : makeBadge(new Date(t.sla_due_at).toLocaleDateString(), "text-bg-light text-dark border")
    );

    tr.addEventListener("click", () => openTicketDetail(t.id));
    tr.append(tdChk, th, tdPrio, tdStatus, tdGroup, tdAssign, tdSla);
    tbody.append(tr);
  }
  syncBulkBar();
}

/* ---------- Dedicated Ticket Detail View ---------- */
async function openTicketDetail(ticketId) {
  selectedTicketId = ticketId;
  showView("detail");
  await refreshLookups();
  const detail = await apiFetch(`/api/v1/tickets/${ticketId}`);

  document.getElementById("detail-key").textContent = detail.ticket_key;
  document.getElementById("detail-title").textContent = detail.title;
  document.getElementById("detail-desc").textContent = detail.description;

  const stPill = document.getElementById("detail-status-pill");
  stPill.className = `badge ${STATUS_BADGES[detail.status] || "text-bg-secondary"}`;
  stPill.textContent = detail.status;

  const prPill = document.getElementById("detail-priority-pill");
  prPill.className = `badge ${PRIORITY_BADGES[detail.priority] || "text-bg-secondary"}`;
  prPill.textContent = detail.priority;

  const slaPill = document.getElementById("detail-sla-pill");
  slaPill.className = `badge ${detail.sla_breached ? "text-bg-danger" : "text-bg-success"}`;
  slaPill.textContent = detail.sla_breached ? "SLA BREACHED" : `SLA OK · ${formatUtc(detail.sla_due_at)}`;

  document.getElementById("edit-title-input").value = detail.title;
  document.getElementById("edit-desc-input").value = detail.description;
  document.getElementById("edit-ticket-form").classList.add("d-none");
  document.getElementById("detail-desc").classList.remove("d-none");

  const isStaff = currentUser.role === "AGENT" || currentUser.role === "ADMIN";
  document.getElementById("internal-note-toggle-wrap").classList.toggle("d-none", !isStaff);
  document.getElementById("save-triage-btn").classList.toggle("d-none", !isStaff);

  const statusSel = document.getElementById("triage-status");
  statusSel.replaceChildren();
  for (const s of TRANSITION_OPTIONS[detail.status] || [detail.status]) {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    opt.selected = s === detail.status;
    statusSel.append(opt);
  }
  statusSel.disabled = !isStaff;

  const prioSel = document.getElementById("triage-priority");
  prioSel.value = detail.priority;
  prioSel.disabled = !isStaff;

  const grpSel = document.getElementById("triage-group");
  grpSel.replaceChildren();
  const noneGrp = document.createElement("option");
  noneGrp.value = "";
  noneGrp.textContent = "Unassigned";
  grpSel.append(noneGrp);
  for (const g of groupsCache) {
    const opt = document.createElement("option");
    opt.value = String(g.id);
    opt.textContent = g.name;
    opt.selected = g.id === detail.group_id;
    grpSel.append(opt);
  }
  grpSel.disabled = !isStaff;

  const assignSel = document.getElementById("triage-assignee");
  assignSel.replaceChildren();
  const unOpt = document.createElement("option");
  unOpt.value = "";
  unOpt.textContent = "Unassigned";
  assignSel.append(unOpt);
  if (isStaff) {
    for (const st of staffDirectory) {
      const opt = document.createElement("option");
      opt.value = String(st.id);
      opt.textContent = `${st.full_name} (${st.role})`;
      opt.selected = st.id === detail.assigned_to_id;
      assignSel.append(opt);
    }
  } else if (detail.assigned_to_name) {
    const opt = document.createElement("option");
    opt.value = String(detail.assigned_to_id || "");
    opt.textContent = detail.assigned_to_name;
    opt.selected = true;
    assignSel.append(opt);
  }
  assignSel.disabled = !isStaff;

  document.getElementById("prop-creator").textContent = detail.created_by_name;
  document.getElementById("prop-created").textContent = formatUtc(detail.created_at);
  document.getElementById("prop-updated").textContent = formatUtc(detail.updated_at);
  document.getElementById("sla-ack-target").textContent = formatDuration(detail.target_ack_minutes);
  document.getElementById("sla-ack-actual").textContent = detail.acknowledged_at
    ? formatUtc(detail.acknowledged_at)
    : "Pending";
  document.getElementById("sla-res-target").textContent = formatDuration(detail.target_resolve_minutes);
  document.getElementById("sla-due-text").textContent = formatUtc(detail.sla_due_at);

  document.getElementById("notes-count-badge").textContent = String(detail.comments.length);
  document.getElementById("attachments-count-badge").textContent = String(detail.attachments.length);
  document.getElementById("audit-count-badge").textContent = String(detail.audit_events.length);

  const commentsEl = document.getElementById("comments-list");
  commentsEl.replaceChildren();
  if (!detail.comments.length) {
    const p = document.createElement("p");
    p.className = "small td-muted";
    p.textContent = "No notes posted yet.";
    commentsEl.append(p);
  } else {
    for (const c of detail.comments) {
      const box = document.createElement("div");
      box.className = `p-3 rounded small ${c.is_internal ? "comment-internal" : "comment-public"}`;
      const top = document.createElement("div");
      top.className = "d-flex justify-content-between fw-semibold mb-1";
      const author = document.createElement("span");
      author.textContent = `${c.author_name} (${c.author_role})${c.is_internal ? " · INTERNAL NOTE" : ""}`;
      const ts = document.createElement("span");
      ts.className = "td-muted fw-normal";
      ts.textContent = formatUtc(c.created_at);
      top.append(author, ts);
      const body = document.createElement("div");
      body.textContent = c.body;
      box.append(top, body);
      commentsEl.append(box);
    }
  }

  const attEl = document.getElementById("attachments-list");
  attEl.replaceChildren();
  if (!detail.attachments.length) {
    const li = document.createElement("li");
    li.className = "list-group-item td-muted";
    li.textContent = "No files attached.";
    attEl.append(li);
  } else {
    for (const a of detail.attachments) {
      const li = document.createElement("li");
      li.className = "list-group-item d-flex justify-content-between align-items-center";
      const meta = document.createElement("span");
      meta.textContent = `${a.original_filename} (${Math.max(1, Math.round(a.size_bytes / 1024))} KB) — ${a.uploaded_by_name}`;
      const dl = document.createElement("button");
      dl.type = "button";
      dl.className = "btn btn-sm btn-outline-primary";
      dl.textContent = "Download";
      dl.addEventListener("click", async () => {
        const res = await fetch(`/api/v1/attachments/${a.id}`, {
          headers: { Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY)}` },
        });
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = a.original_filename;
        link.click();
        URL.revokeObjectURL(url);
      });
      li.append(meta, dl);
      attEl.append(li);
    }
  }

  const auditEl = document.getElementById("audit-list");
  auditEl.replaceChildren();
  for (const ev of detail.audit_events) {
    const li = document.createElement("li");
    li.className = "list-group-item";
    const desc = ev.old_value
      ? `${ev.event_type} ${ev.field_name}: ${ev.old_value} -> ${ev.new_value}`
      : `${ev.event_type} (${ev.field_name || "event"}): ${ev.new_value || ""}`;
    li.textContent = `${formatUtc(ev.created_at)} · ${ev.actor_name} — ${desc}`;
    auditEl.append(li);
  }
}

/* ---------- Admin & Management Views ---------- */
async function loadUsersView() {
  const users = await apiFetch("/api/v1/users");
  const tbody = document.getElementById("admin-users-tbody");
  tbody.replaceChildren();
  for (const u of users) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = u.full_name;
    const tdEmail = document.createElement("td");
    tdEmail.textContent = u.email;
    const tdRole = document.createElement("td");
    tdRole.append(makeBadge(u.role, "text-bg-primary"));
    const tdAct = document.createElement("td");
    const sel = document.createElement("select");
    sel.className = "form-select form-select-sm w-auto";
    for (const r of ["CUSTOMER", "AGENT", "ADMIN"]) {
      const opt = document.createElement("option");
      opt.value = r;
      opt.textContent = r;
      opt.selected = r === u.role;
      sel.append(opt);
    }
    sel.addEventListener("change", async () => {
      await apiFetch(`/api/v1/users/${u.id}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role: sel.value }),
      });
      showAlert(`Updated role for ${u.full_name} to ${sel.value}.`, "success");
      await loadUsersView();
    });
    tdAct.append(sel);
    tr.append(th, tdEmail, tdRole, tdAct);
    tbody.append(tr);
  }
}

async function loadGroupsView() {
  const groups = await apiFetch("/api/v1/groups");
  const list = document.getElementById("groups-list");
  list.replaceChildren();
  for (const g of groups) {
    const li = document.createElement("li");
    li.className = "list-group-item d-flex justify-content-between align-items-center";
    const info = document.createElement("div");
    const name = document.createElement("div");
    name.className = "fw-semibold";
    name.textContent = g.name;
    const desc = document.createElement("div");
    desc.className = "small td-muted";
    desc.textContent = g.description || "Support routing queue";
    info.append(name, desc);
    li.append(info);
    if (currentUser.role === "ADMIN") {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "btn btn-sm btn-outline-danger";
      del.textContent = "Delete";
      del.addEventListener("click", async () => {
        await apiFetch(`/api/v1/groups/${g.id}`, { method: "DELETE" });
        await loadGroupsView();
      });
      li.append(del);
    }
    list.append(li);
  }
}

async function loadApiKeysView() {
  const keys = await apiFetch("/api/v1/api-keys");
  const list = document.getElementById("apikeys-list");
  list.replaceChildren();
  if (!keys.length) {
    const li = document.createElement("li");
    li.className = "list-group-item td-muted small";
    li.textContent = "No API keys created yet.";
    list.append(li);
    return;
  }
  for (const k of keys) {
    const li = document.createElement("li");
    li.className = "list-group-item d-flex justify-content-between align-items-center";
    const left = document.createElement("div");
    const title = document.createElement("div");
    title.className = "fw-semibold";
    title.textContent = `${k.name} (${k.key_prefix}...)`;
    const sub = document.createElement("div");
    sub.className = "small td-muted";
    sub.textContent = `Owner: ${k.owner_name} · ${k.is_active ? "Active" : "Revoked"}`;
    left.append(title, sub);
    li.append(left);
    if (k.is_active) {
      const rev = document.createElement("button");
      rev.type = "button";
      rev.className = "btn btn-sm btn-outline-danger";
      rev.textContent = "Revoke";
      rev.addEventListener("click", async () => {
        await apiFetch(`/api/v1/api-keys/${k.id}`, { method: "DELETE" });
        await loadApiKeysView();
      });
      li.append(rev);
    }
    list.append(li);
  }
}

async function loadSlaView() {
  const policies = await apiFetch("/api/v1/sla");
  const grid = document.getElementById("sla-grid");
  grid.replaceChildren();
  const isAdmin = currentUser.role === "ADMIN";
  for (const p of policies) {
    const col = document.createElement("div");
    col.className = "col-12 col-md-6 col-xl-3";
    const card = document.createElement("div");
    card.className = "card td-card h-100";
    const body = document.createElement("div");
    body.className = "card-body";
    const badge = makeBadge(p.priority, PRIORITY_BADGES[p.priority]);
    const form = document.createElement("form");
    form.className = "mt-3 d-flex flex-column gap-2";

    const ackLbl = document.createElement("label");
    ackLbl.className = "form-label small td-muted mb-0";
    ackLbl.textContent = "Target Ack / MTTA (minutes)";
    const ackIn = document.createElement("input");
    ackIn.type = "number";
    ackIn.min = "1";
    ackIn.className = "form-control form-control-sm";
    ackIn.value = String(p.target_ack_minutes);
    ackIn.disabled = !isAdmin;

    const resLbl = document.createElement("label");
    resLbl.className = "form-label small td-muted mb-0";
    resLbl.textContent = "Target Resolve / MTTR (minutes)";
    const resIn = document.createElement("input");
    resIn.type = "number";
    resIn.min = "5";
    resIn.className = "form-control form-control-sm";
    resIn.value = String(p.target_resolve_minutes);
    resIn.disabled = !isAdmin;

    form.append(ackLbl, ackIn, resLbl, resIn);
    if (isAdmin) {
      const saveBtn = document.createElement("button");
      saveBtn.type = "submit";
      saveBtn.className = "btn btn-primary btn-sm mt-2 fw-semibold";
      saveBtn.textContent = "Save SLA";
      form.append(saveBtn);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        saveBtn.disabled = true;
        try {
          await apiFetch(`/api/v1/sla/${p.priority}`, {
            method: "PUT",
            body: JSON.stringify({
              target_ack_minutes: Number(ackIn.value),
              target_resolve_minutes: Number(resIn.value),
            }),
          });
          showAlert(`Saved SLA targets for ${p.priority}.`, "success");
        } catch (err) {
          showAlert(err.message);
        } finally {
          saveBtn.disabled = false;
        }
      });
    }
    body.append(badge, form);
    card.append(body);
    col.append(card);
    grid.append(col);
  }
}

/* ---------- Event Wiring (Capturing form refs synchronously before await!) ---------- */
document.getElementById("theme-toggle-btn").addEventListener("click", toggleColorScheme);
document.getElementById("open-sidebar-btn").addEventListener("click", () => {
  document.querySelector(".td-sidebar").classList.add("open");
});
document.getElementById("close-sidebar-btn").addEventListener("click", () => {
  document.querySelector(".td-sidebar").classList.remove("open");
});

document.querySelectorAll(".td-nav-item").forEach((btn) => {
  btn.addEventListener("click", () => navigateTo(btn.dataset.view));
});

document.getElementById("dash-new-ticket-btn").addEventListener("click", async () => {
  await navigateTo("tickets");
  document.getElementById("create-ticket-card").classList.remove("d-none");
  document.getElementById("ticket-title").focus();
});

document.getElementById("mode-login-btn").addEventListener("click", () => {
  document.getElementById("login-form").classList.remove("d-none");
  document.getElementById("register-form").classList.add("d-none");
  document.getElementById("mode-login-btn").classList.add("active");
  document.getElementById("mode-register-btn").classList.remove("active");
  document.getElementById("auth-heading").textContent = "Sign in";
});

document.getElementById("mode-register-btn").addEventListener("click", () => {
  document.getElementById("login-form").classList.add("d-none");
  document.getElementById("register-form").classList.remove("d-none");
  document.getElementById("mode-register-btn").classList.add("active");
  document.getElementById("mode-login-btn").classList.remove("active");
  document.getElementById("auth-heading").textContent = "Create Customer Account";
});

document.getElementById("toggle-login-pw").addEventListener("click", () => {
  const input = document.getElementById("login-password");
  const btn = document.getElementById("toggle-login-pw");
  const hidden = input.type === "password";
  input.type = hidden ? "text" : "password";
  btn.textContent = hidden ? "Hide" : "Show";
});

async function performLogin(email, password) {
  showAlert("");
  const data = await apiFetch("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  currentUser = data.user;
  selectedTicketId = null;
  selectedBulkIds.clear();
  renderShell();
  await navigateTo("dashboard");
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!form.reportValidity()) return;
  submitBtn.disabled = true;
  try {
    await performLogin(
      document.getElementById("login-email").value,
      document.getElementById("login-password").value
    );
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!form.reportValidity()) return;
  showAlert("");
  submitBtn.disabled = true;
  try {
    const data = await apiFetch("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({
        full_name: document.getElementById("reg-name").value,
        email: document.getElementById("reg-email").value,
        password: document.getElementById("reg-password").value,
      }),
    });
    localStorage.setItem(TOKEN_KEY, data.access_token);
    currentUser = data.user;
    form.reset();
    renderShell();
    await navigateTo("dashboard");
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.querySelectorAll(".demo-login-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    performLogin(btn.dataset.email, "DemoPass123!").catch((err) => showAlert(err.message));
  });
});

document.getElementById("logout-btn").addEventListener("click", () => {
  localStorage.removeItem(TOKEN_KEY);
  currentUser = null;
  selectedTicketId = null;
  selectedBulkIds.clear();
  renderShell();
});

document.getElementById("toggle-create-btn").addEventListener("click", () => {
  document.getElementById("create-ticket-card").classList.toggle("d-none");
});
document.getElementById("close-create-btn").addEventListener("click", () => {
  document.getElementById("create-ticket-card").classList.add("d-none");
});
document.getElementById("refresh-tickets-btn").addEventListener("click", () => loadTicketsView());
document.getElementById("back-to-tickets-btn").addEventListener("click", () => navigateTo("tickets"));

["filter-search", "filter-status", "filter-priority", "filter-group", "filter-assigned-me"].forEach((id) => {
  document.getElementById(id).addEventListener("input", () => loadTicketsView());
  document.getElementById(id).addEventListener("change", () => loadTicketsView());
});

document.getElementById("select-all-tickets").addEventListener("change", (e) => {
  const checked = e.currentTarget.checked;
  document.querySelectorAll(".ticket-bulk-cb").forEach((cb) => {
    cb.checked = checked;
    cb.dispatchEvent(new Event("change"));
  });
});

document.getElementById("bulk-clear-btn").addEventListener("click", () => {
  selectedBulkIds.clear();
  document.getElementById("select-all-tickets").checked = false;
  loadTicketsView();
});

document.getElementById("bulk-apply-btn").addEventListener("click", async () => {
  const st = document.getElementById("bulk-status").value || null;
  const pr = document.getElementById("bulk-priority").value || null;
  const asg = document.getElementById("bulk-assignee").value;
  if (!st && !pr && !asg) {
    showAlert("Choose at least one status, priority, or assignee for bulk update.");
    return;
  }
  try {
    await apiFetch("/api/v1/tickets/bulk", {
      method: "POST",
      body: JSON.stringify({
        ticket_ids: [...selectedBulkIds],
        status: st,
        priority: pr,
        assigned_to_id: asg ? Number(asg) : null,
      }),
    });
    selectedBulkIds.clear();
    document.getElementById("select-all-tickets").checked = false;
    showAlert("Bulk triage updates applied.", "success");
    await loadTicketsView();
  } catch (err) {
    showAlert(err.message);
  }
});

document.getElementById("create-ticket-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!form.reportValidity()) return;

  const groupVal = document.getElementById("ticket-group").value;
  submitBtn.disabled = true;
  try {
    const created = await apiFetch("/api/v1/tickets", {
      method: "POST",
      body: JSON.stringify({
        title: document.getElementById("ticket-title").value,
        category: document.getElementById("ticket-category").value,
        priority: document.getElementById("ticket-priority").value,
        group_id: groupVal ? Number(groupVal) : null,
        description: document.getElementById("ticket-desc").value,
      }),
    });
    form.reset();
    document.getElementById("create-ticket-card").classList.add("d-none");
    await openTicketDetail(created.id);
    showAlert(`Ticket ${created.ticket_key} created successfully.`, "success");
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("edit-desc-toggle-btn").addEventListener("click", () => {
  document.getElementById("detail-desc").classList.add("d-none");
  document.getElementById("edit-ticket-form").classList.remove("d-none");
});
document.getElementById("cancel-edit-btn").addEventListener("click", () => {
  document.getElementById("edit-ticket-form").classList.add("d-none");
  document.getElementById("detail-desc").classList.remove("d-none");
});

document.getElementById("edit-ticket-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!selectedTicketId || !form.reportValidity()) return;
  submitBtn.disabled = true;
  try {
    await apiFetch(`/api/v1/tickets/${selectedTicketId}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: document.getElementById("edit-title-input").value,
        description: document.getElementById("edit-desc-input").value,
      }),
    });
    await openTicketDetail(selectedTicketId);
    showAlert("Ticket details updated.", "success");
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("triage-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = document.getElementById("save-triage-btn");
  if (!selectedTicketId) return;
  const assignVal = document.getElementById("triage-assignee").value;
  const groupVal = document.getElementById("triage-group").value;
  submitBtn.disabled = true;
  try {
    await apiFetch(`/api/v1/tickets/${selectedTicketId}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: document.getElementById("triage-status").value,
        priority: document.getElementById("triage-priority").value,
        assigned_to_id: assignVal ? Number(assignVal) : null,
        unassign: !assignVal,
        group_id: groupVal ? Number(groupVal) : null,
        clear_group: !groupVal,
      }),
    });
    await openTicketDetail(selectedTicketId);
    showAlert("Ticket properties updated.", "success");
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("comment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!selectedTicketId || !form.reportValidity()) return;
  submitBtn.disabled = true;
  try {
    await apiFetch(`/api/v1/tickets/${selectedTicketId}/comments`, {
      method: "POST",
      body: JSON.stringify({
        body: document.getElementById("comment-body").value,
        is_internal: document.getElementById("comment-internal").checked,
      }),
    });
    form.reset();
    await openTicketDetail(selectedTicketId);
    showAlert("Message posted.", "success");
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("attachment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  const fileInput = document.getElementById("attachment-file");
  if (!selectedTicketId || !fileInput.files?.length) return;
  const body = new FormData();
  body.append("file", fileInput.files[0]);
  submitBtn.disabled = true;
  try {
    await apiFetch(`/api/v1/tickets/${selectedTicketId}/attachments`, { method: "POST", body });
    form.reset();
    await openTicketDetail(selectedTicketId);
    showAlert("Attachment uploaded.", "success");
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("create-group-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!form.reportValidity()) return;
  submitBtn.disabled = true;
  try {
    await apiFetch("/api/v1/groups", {
      method: "POST",
      body: JSON.stringify({
        name: document.getElementById("group-name").value,
        description: document.getElementById("group-desc").value,
      }),
    });
    form.reset();
    showAlert("Support group added.", "success");
    await loadGroupsView();
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("create-apikey-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  if (!form.reportValidity()) return;
  submitBtn.disabled = true;
  try {
    const created = await apiFetch("/api/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: document.getElementById("apikey-name").value }),
    });
    form.reset();
    const banner = document.getElementById("new-api-key-banner");
    banner.textContent = `New API Key (${created.name}) — copy now, shown once: ${created.raw_key}`;
    banner.classList.remove("d-none");
    await loadApiKeysView();
  } catch (err) {
    showAlert(err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

/* ---------- Startup Session Restore ---------- */
(async () => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    renderShell();
    return;
  }
  try {
    currentUser = await apiFetch("/api/v1/auth/me");
    renderShell();
    await navigateTo("dashboard");
  } catch {
    renderShell();
  }
})();
