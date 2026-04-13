const INDEX_PATH = "../data/projected/graph-v1/views/index.json";

const state = {
  index: null,
  currentViewId: null,
  viewCache: new Map(),
};

const navEl = document.getElementById("view-nav");
const titleEl = document.getElementById("view-title");
const eyebrowEl = document.getElementById("view-eyebrow");
const generatedAtEl = document.getElementById("generated-at");
const metricsEl = document.getElementById("metrics");
const contentEl = document.getElementById("content");
const rawJsonLinkEl = document.getElementById("raw-json-link");
const metricTemplate = document.getElementById("metric-card-template");

function formatNumber(value) {
  if (typeof value !== "number") return value ?? "—";
  return new Intl.NumberFormat("en-US").format(value);
}

function formatDate(value) {
  if (!value || typeof value !== "string") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function badge(text, variant = "") {
  const node = el("span", `badge${variant ? ` badge--${variant}` : ""}`, text);
  return node;
}

function createMetricCards(metrics) {
  clearChildren(metricsEl);
  Object.entries(metrics || {}).forEach(([key, value]) => {
    const fragment = metricTemplate.content.cloneNode(true);
    fragment.querySelector(".metric-card__label").textContent = key.replaceAll("_", " ");
    fragment.querySelector(".metric-card__value").textContent =
      typeof value === "object" ? JSON.stringify(value) : formatNumber(value);
    metricsEl.appendChild(fragment);
  });
}

function renderProperties(properties) {
  const dl = el("dl", "kv");
  Object.entries(properties || {}).forEach(([key, value]) => {
    const dt = el("dt", null, key.replaceAll("_", " "));
    const dd = el("dd");
    dd.textContent = Array.isArray(value) ? value.join(", ") : String(value);
    dl.append(dt, dd);
  });
  return dl;
}

function renderNodeCard(node) {
  const card = el("article", "node-card");
  card.append(
    el("p", "eyebrow", node.node_type),
    el("h4", null, node.display_label),
  );
  const meta = el("div", "node-card__meta");
  if (node.year) meta.append(badge(String(node.year)));
  meta.append(badge(node.id, "accent"));
  card.append(meta);
  if (node.properties && Object.keys(node.properties).length) {
    card.append(renderProperties(node.properties));
  }
  return card;
}

function renderListSection(title, items, renderer = renderNodeCard, options = {}) {
  const { open = false, emptyMessage = "No items." } = options;
  const details = document.createElement("details");
  details.className = "panel";
  details.open = open;
  const summary = document.createElement("summary");
  summary.textContent = `${title} (${items.length})`;
  details.append(summary);
  if (!items.length) {
    details.append(el("div", "empty-state", emptyMessage));
    return details;
  }
  const stack = el("div", "stack");
  items.forEach((item) => stack.append(renderer(item)));
  details.append(stack);
  return details;
}

function renderVoteRow(vote) {
  const row = el("article", "vote-row");
  const left = el("div");
  left.append(
    el("div", null, vote.actor_label),
    el("div", "muted", `${vote.meeting_date || "undated"} · ${vote.decision_label}`)
  );
  const right = el("div", "pill-row");
  right.append(badge(vote.vote || "vote", vote.vote === "yes" ? "ok" : "accent"));
  if (vote.seat_id) right.append(badge(vote.seat_id));
  row.append(left, right);
  return row;
}

function renderMoneyFlowEdge(item) {
  const card = el("article", "list-card");
  const flow = item.money_flow;
  card.append(
    el("p", "eyebrow", (item.relationship_types || [item.relationship_type || "linked"]).join(" · ")),
    el("h4", null, flow.display_label)
  );
  const meta = el("div", "list-card__meta");
  meta.append(badge(flow.id, "accent"));
  if (flow.properties?.flow_type) meta.append(badge(flow.properties.flow_type));
  if (flow.properties?.money_type) meta.append(badge(flow.properties.money_type));
  if (flow.properties?.amount !== undefined) meta.append(badge(`$${formatNumber(flow.properties.amount)}`));
  card.append(meta);
  if (flow.properties) card.append(renderProperties(flow.properties));
  return card;
}

function renderOverlapSubject(item) {
  const card = el("article", "list-card");
  card.append(
    el("p", "eyebrow", item.node.node_type),
    el("h4", null, item.node.display_label)
  );
  const pills = el("div", "pill-row");
  pills.append(badge(`${item.flow_count} flows`, "ok"));
  item.flow_types.forEach((value) => pills.append(badge(value)));
  card.append(pills);
  card.append(renderProperties({
    id: item.node.id,
    relationship_types: item.relationship_types.join(", "),
    source_bundle_ids: item.source_bundle_ids.join(", "),
  }));
  return card;
}

function renderValidationItem(item) {
  const node = item.check;
  const wrapper = el("article", "queue-item");
  const header = el("div", "queue-item__header");
  const left = el("div");
  left.append(
    el("p", "eyebrow", item.metric_name || node.properties.metric_name || "validation check"),
    el("h4", null, item.subject?.display_label || node.display_label),
  );
  const right = el("div", "pill-row");
  right.append(badge(item.status || "unknown", item.status === "reconciled" ? "ok" : "warn"));
  right.append(badge(item.severity || "info"));
  header.append(left, right);
  wrapper.append(header);
  wrapper.append(
    renderProperties({
      check_id: node.id,
      subject_id: item.subject?.id,
      derived_record_id: item.derived_record?.id,
      measured_value: item.measured_value_number,
      reference_value: item.reference_value_number,
      absolute_delta: item.absolute_delta_value_number,
    })
  );
  return wrapper;
}

function renderRollupCard(item) {
  const subject = item.program || item.project;
  const secondary = item.institution || item.primary_place;
  const wrapper = el("article", "list-card");
  wrapper.append(
    el("p", "eyebrow", subject?.node_type || "Rollup"),
    el("h4", null, subject?.display_label || "Unnamed")
  );
  const pills = el("div", "pill-row");
  Object.entries(item.metrics || {}).forEach(([key, value]) => {
    if (typeof value !== "number") return;
    pills.append(badge(`${formatNumber(value)} ${key.replaceAll("_count", "").replaceAll("_", " ")}`));
  });
  wrapper.append(pills);
  if (secondary) {
    wrapper.append(el("p", "muted", secondary.display_label));
  }
  return wrapper;
}

function renderActorDossier(data) {
  contentEl.append(
    renderListSection("Actor", [data.actor], renderNodeCard, { open: true }),
    renderListSection("Seat Services", data.seat_services),
    renderListSection("Committees", data.committees),
    renderListSection("Candidacies", data.candidacies || []),
    renderListSection("Filings", data.filings),
    renderListSection("Council Votes", data.council_votes, renderVoteRow),
    renderListSection("Money Flows", data.money_flows, renderMoneyFlowEdge),
    renderListSection("Evidence Records", data.evidence_records || []),
    renderListSection("Related Records", data.related_records || [])
  );
}

function renderDecisionDossier(data) {
  contentEl.append(
    renderListSection("Decision", [data.decision], renderNodeCard, { open: true }),
    renderListSection("Meeting", [data.meeting], renderNodeCard, { open: true }),
    renderListSection("Agenda Items", data.agenda_items),
    renderListSection("Votes", data.votes.map((vote) => ({
      actor_label: vote.actor_label,
      meeting_date: data.meeting?.properties?.meeting_date,
      decision_label: data.decision.display_label,
      vote: vote.vote,
      seat_id: vote.seat_id,
    })), renderVoteRow),
    renderListSection("Evidence Records", data.evidence_records),
    renderListSection("Linked Money Flows", data.linked_money_flows),
    renderListSection("Linked Cases", data.linked_cases),
    renderListSection("Linked Programs", data.linked_programs),
  );
}

function renderOrganizationDossier(data) {
  contentEl.append(
    renderListSection("Organization", [data.organization], renderNodeCard, { open: true }),
    renderListSection("Money Flows", data.money_flows || [], renderMoneyFlowEdge, { open: true }),
    renderListSection("Linked Decisions", data.linked_decisions || []),
    renderListSection("Evidence Records", data.evidence_records || []),
    renderListSection("Related Records", data.related_records || []),
    renderListSection("Linked Cases", data.linked_cases || []),
    renderListSection("Linked Programs", data.linked_programs || []),
  );
}

function renderCaseDossier(data) {
  contentEl.append(
    renderListSection("Case", [data.case], renderNodeCard, { open: true }),
    renderListSection("Court", data.court ? [data.court] : []),
    renderListSection("Proceedings", data.proceedings || [], renderNodeCard, { open: true }),
    renderListSection("Participations", data.participations || []),
    renderListSection("Evidence Records", data.evidence_records || []),
    renderListSection("Related Records", data.related_records || []),
    renderListSection("Issues", data.issues || []),
    renderListSection("Programs", data.programs || []),
    renderListSection("Places", data.places || []),
    renderListSection("Linked Local Decisions", data.linked_local_decisions || []),
  );
}

function renderProgramDossier(data) {
  contentEl.append(
    renderListSection("Program", [data.program], renderNodeCard, { open: true }),
    renderListSection("Institution", data.institution ? [data.institution] : []),
    renderListSection("Jurisdiction", data.jurisdiction_place ? [data.jurisdiction_place] : []),
    renderListSection("Places", data.places || []),
    renderListSection("Evidence Records", data.evidence_records || []),
    renderListSection("Related Records", data.related_records || []),
    renderListSection("Linked Cases", data.linked_cases || []),
    renderListSection("Linked Decisions", data.linked_decisions || []),
    renderListSection("Linked Money Flows", data.linked_money_flows || []),
  );
}

function renderProjectDossier(data) {
  contentEl.append(
    renderListSection("Project", [data.project], renderNodeCard, { open: true }),
    renderListSection("Primary Place", data.primary_place ? [data.primary_place] : []),
    renderListSection("Jurisdiction", data.jurisdiction_place ? [data.jurisdiction_place] : []),
    renderListSection("Evidence Records", data.evidence_records || []),
    renderListSection("Related Records", data.related_records || []),
    renderListSection("Linked Programs", data.linked_programs || []),
    renderListSection("Linked Decisions", data.linked_decisions || []),
    renderListSection("Agreements", data.agreements || []),
    renderListSection("Amendments", data.amendments || []),
    renderListSection("Linked Money Flows", data.linked_money_flows || []),
  );
}

function renderMoneyOverlap(data) {
  contentEl.append(
    renderListSection("Top Overlap Subjects", data.top_overlap_subjects, renderOverlapSubject, { open: true })
  );
}

function renderJurisdictionDeliverySummary(data) {
  contentEl.append(
    renderListSection("Jurisdiction", [data.jurisdiction_place], renderNodeCard, { open: true }),
    renderListSection("Program Rollups", data.program_rollups || [], renderRollupCard, { open: true }),
    renderListSection("Project Rollups", data.project_rollups || [], renderRollupCard, { open: true }),
    renderListSection("Linked Decisions", data.linked_decisions || []),
    renderListSection("Linked Money Flows", data.linked_money_flows || []),
    renderListSection("Linked Cases", data.linked_cases || []),
    renderListSection("Evidence Records", data.evidence_records || []),
    renderListSection("Related Records", data.related_records || []),
  );
}

function renderLegalConstraint(data) {
  const panel = el("section", "panel");
  panel.append(el("h3", null, "Case Views"));
  const stack = el("div", "stack");
  data.case_views.forEach((caseView) => {
    const details = document.createElement("details");
    details.className = "panel";
    const summary = document.createElement("summary");
    summary.textContent = caseView.case.display_label;
    details.append(summary);
    const grid = el("div", "panel-grid");
    grid.append(renderNodeCard(caseView.case));
    if (caseView.issues.length) {
      const issues = el("div", "panel");
      issues.append(el("h3", null, "Issues"));
      issues.append(...caseView.issues.map(renderNodeCard));
      grid.append(issues);
    }
    const sections = [
      ["Proceedings", caseView.proceedings],
      ["Participations", caseView.participations],
      ["Records", caseView.records],
      ["Programs", caseView.programs],
      ["Linked Local Decisions", caseView.linked_local_decisions],
    ];
    sections.forEach(([title, items]) => {
      if (!items.length) return;
      const section = el("div", "panel");
      section.append(el("h3", null, title));
      const inner = el("div", "stack");
      items.forEach((item) => inner.append(renderNodeCard(item)));
      section.append(inner);
      grid.append(section);
    });
    details.append(grid);
    stack.append(details);
  });
  panel.append(stack);
  contentEl.append(panel);
}

function renderValidationQueue(data) {
  contentEl.append(
    renderListSection("Validation Items", data.items, renderValidationItem, { open: true })
  );
}

function renderView(data) {
  clearChildren(contentEl);
  createMetricCards(data.metrics || {});

  if (data.view_type === "actor_dossier") {
    renderActorDossier(data);
    return;
  }
  if (data.view_type === "organization_dossier") {
    renderOrganizationDossier(data);
    return;
  }
  if (data.view_type === "decision_dossier") {
    renderDecisionDossier(data);
    return;
  }
  if (data.view_type === "case_dossier") {
    renderCaseDossier(data);
    return;
  }
  if (data.view_type === "program_dossier") {
    renderProgramDossier(data);
    return;
  }
  if (data.view_type === "project_dossier") {
    renderProjectDossier(data);
    return;
  }
  if (data.view_type === "money_overlap_summary") {
    renderMoneyOverlap(data);
    return;
  }
  if (data.view_type === "jurisdiction_delivery_summary") {
    renderJurisdictionDeliverySummary(data);
    return;
  }
  if (data.view_type === "legal_constraint_view") {
    renderLegalConstraint(data);
    return;
  }
  if (data.view_type === "validation_queue") {
    renderValidationQueue(data);
    return;
  }

  contentEl.append(el("div", "empty-state", "Unknown view payload."));
}

function setActiveNav() {
  [...navEl.querySelectorAll(".nav-button")].forEach((button) => {
    button.classList.toggle("is-active", button.dataset.viewId === state.currentViewId);
  });
}

async function loadView(viewId) {
  const viewMeta = state.index.views.find((view) => view.id === viewId);
  if (!viewMeta) return;

  state.currentViewId = viewId;
  setActiveNav();
  rawJsonLinkEl.href = `../${viewMeta.path}`;

  let data = state.viewCache.get(viewId);
  if (!data) {
    const response = await fetch(`../${viewMeta.path}`);
    if (!response.ok) throw new Error(`Failed to fetch ${viewMeta.path}`);
    data = await response.json();
    state.viewCache.set(viewId, data);
  }

  eyebrowEl.textContent = "Projected View";
  titleEl.textContent = data.title;
  generatedAtEl.textContent = `Generated ${formatDate(data.generated_at)}`;
  renderView(data);
  window.location.hash = viewId;
}

function renderNav() {
  clearChildren(navEl);
  state.index.views.forEach((view) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nav-button";
    button.dataset.viewId = view.id;
    button.addEventListener("click", () => loadView(view.id));

    button.append(
      el("span", "nav-button__title", view.title),
      el("span", "nav-button__id", view.view_type || view.id),
    );
    navEl.append(button);
  });
  setActiveNav();
}

async function bootstrap() {
  const response = await fetch(INDEX_PATH);
  if (!response.ok) throw new Error(`Failed to fetch ${INDEX_PATH}`);
  state.index = await response.json();
  renderNav();
  const requested = window.location.hash.replace(/^#/, "");
  const initial = state.index.views.find((view) => view.id === requested)?.id || state.index.views[0]?.id;
  if (initial) await loadView(initial);
}

bootstrap().catch((error) => {
  titleEl.textContent = "Viewer failed to load";
  generatedAtEl.textContent = "";
  clearChildren(metricsEl);
  clearChildren(contentEl);
  contentEl.append(el("div", "empty-state", error.message));
  console.error(error);
});
