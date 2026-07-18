const controlTokenMeta = document.querySelector('meta[name="ticketbox-control-token"]');
window.CONTROL_TOKEN = controlTokenMeta?.content || "";
controlTokenMeta?.remove();

const $ = (id) => document.getElementById(id);
const workspaceControls = [...document.querySelectorAll(".workspace-control")];
const workspaceOrder = ["inbox", "transactions", "obligations", "plans", "insights"];
const compactInspectorMedia = window.matchMedia("(max-width: 1007px)");
const inspectorFocusableSelector = [
  "button:not([hidden]):not([disabled])",
  "input:not([hidden]):not([disabled])",
  "select:not([hidden]):not([disabled])",
  "a[href]:not([hidden])",
  '[tabindex]:not([tabindex="-1"])'
].join(",");
const roleLabels = {
  owner: "所有者",
  member: "可编辑",
  viewer: "只读"
};
const workspaceMeta = {
  inbox: {
    index: "01",
    kicker: "待整理记录",
    title: "收件",
    summary: "整理待确认记录，选择一项即可补全、确认或忽略。"
  },
  transactions: {
    index: "02",
    kicker: "已入账记录",
    title: "流水",
    summary: "查看已入账记录，快速核对商家、分类、金额与时间。"
  },
  obligations: {
    index: "03",
    kicker: "往来与余额",
    title: "往来",
    summary: "查看我欠、欠我和家庭垫付，跟进待处理往来。"
  },
  plans: {
    index: "04",
    kicker: "未来安排",
    title: "计划",
    summary: "集中查看预算、目标、收入和固定支出安排。"
  },
  insights: {
    index: "05",
    kicker: "本月事实与数据质量",
    title: "洞察",
    summary: "查看本月事实和数据质量，优先处理需要补齐的事项。"
  }
};
const tableWorkspaceColumns = {
  inbox: [
    {label: "待整理商家", value: (row) => row.title || "待补商家"},
    {label: "分类 / 缺口", value: (row) => row.subtitle || "未分类"},
    {label: "处理状态", value: (row) => row.status_label || row.status || "—", status: true},
    {label: "待确认金额", value: amountText, numeric: true},
    {label: "收到 / 消费时间", value: (row) => timeText(row.occurred_at, row.occurred_precision)}
  ],
  transactions: [
    {label: "入账商家", value: (row) => row.title || "未命名商家"},
    {label: "分类 / 来源", value: (row) => row.subtitle || "未分类"},
    {label: "入账状态", value: (row) => row.status_label || row.status || "—", status: true},
    {label: "已入账金额", value: amountText, numeric: true},
    {label: "消费时间", value: (row) => timeText(row.occurred_at, row.occurred_precision)}
  ],
  obligations: [
    {label: "往来对象", value: (row) => row.title || "未命名往来对象"},
    {label: "当前关系", value: (row) => row.subtitle || "待确认"},
    {label: "结清状态", value: (row) => row.status_label || row.status || "—", status: true},
    {label: "待清算", value: amountText, numeric: true},
    {label: "最近更新", value: (row) => timeText(row.occurred_at, row.occurred_precision)}
  ]
};
const planGroupMeta = {
  budget: {
    title: "本月预算",
    detail: "本月可用约束、已使用和剩余金额。"
  },
  goal: {
    title: "支出目标",
    detail: "需要持续关注的分类或全账本目标。"
  },
  income: {
    title: "收入安排",
    detail: "预计到账和已记录的收入计划。"
  },
  recurring: {
    title: "固定支出",
    detail: "周期性支出与下一次预计日期。"
  }
};

const hashWorkspace = window.location.hash.slice(1);
const state = {
  workspace: workspaceOrder.includes(hashWorkspace) ? hashWorkspace : "inbox",
  ledgerId: "",
  payload: null,
  rows: [],
  visibleRows: [],
  selectedKey: "",
  productAvailable: false,
  principalReady: false,
  principalLoading: false,
  loading: false,
  requestSerial: 0,
  commandBusy: false,
  pendingCommand: null,
  commandNotice: "",
  inspectorOpen: false,
  confirmationResolve: null
};

function managerPath() {
  return "/";
}

function requestHeaders() {
  return {"X-Control-Token": window.CONTROL_TOKEN};
}

function freshIdempotencyKey() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `desktop-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setConnection(kind, text) {
  $("connection").dataset.state = kind;
  $("connectionText").textContent = text;
}

function setStatusPanel(
  title,
  detail,
  {managerAction = false, pairingAction = false} = {}
) {
  $("statusTitle").textContent = title;
  $("statusDetail").textContent = detail;
  $("statusAction").href = managerPath();
  $("statusAction").hidden = !managerAction;
  $("pairingForm").hidden = !pairingAction;
  if (!pairingAction) $("pairingFeedback").textContent = "";
  $("statusPanel").hidden = false;
}

function clearStatusPanel() {
  $("statusPanel").hidden = true;
  $("pairingForm").hidden = true;
  $("pairingFeedback").textContent = "";
}

function setWorkspaceAvailability(available) {
  state.productAvailable = available;
  workspaceControls.forEach((control) => { control.disabled = !available; });
  $("refreshButton").disabled = !available || state.loading;
  $("ledgerSelect").disabled = !available || state.loading || $("ledgerSelect").options.length < 2;
  $("unpairButton").hidden = !state.principalReady;
  $("unpairButton").disabled = state.loading || state.commandBusy;
  setCommandBusy(state.commandBusy);
}

function clearProductData(syncText = "等待同步") {
  state.requestSerial += 1;
  state.loading = false;
  state.payload = null;
  state.rows = [];
  state.visibleRows = [];
  state.selectedKey = "";
  state.ledgerId = "";
  state.pendingCommand = null;
  state.commandNotice = "";
  state.commandBusy = false;
  $("searchInput").value = "";
  $("rowTableBody").replaceChildren();
  $("planGroups").replaceChildren();
  $("insightFact").replaceChildren();
  $("attentionRecords").replaceChildren();
  $("qualityRecords").replaceChildren();
  $("rowCount").textContent = "0 / 0 项";
  $("emptyPanel").hidden = true;
  $("syncNote").textContent = syncText;
  $("roleNote").textContent = "—";
  const option = document.createElement("option");
  option.textContent = "账本未加载";
  $("ledgerSelect").replaceChildren(option);
  $("ledgerSelect").disabled = true;
  $("refreshButton").textContent = "刷新";
  $("commandAmount").value = "";
  $("commandMerchant").value = "";
  $("commandCategory").value = "";
  $("commandAmountLabel").textContent = "金额";
  $("dataStage").setAttribute("aria-busy", "false");
  renderInspector(null);
  setCommandBusy(false);
}

function failClosedProductState(
  message,
  {status = 0, error = "", managerAction = false} = {}
) {
  const principalInvalid = status === 401
    || error === "product_principal_required"
    || error === "invalid_token";
  if (principalInvalid) {
    state.principalReady = false;
    clearProductData("当前未显示账务数据");
    setWorkspaceAvailability(false);
    setConnection("blocked", "桌面账本未绑定");
    setStatusPanel(
      "连接你的桌面账本",
      message || "请在系统管理中生成 8 位绑定码，然后在此完成连接。",
      {managerAction: true, pairingAction: true}
    );
    return;
  }
  if (status === 403 || error === "permission_denied") {
    clearProductData("当前未显示账务数据");
    setWorkspaceAvailability(false);
    setConnection("blocked", "当前身份无权访问");
    setStatusPanel(
      "当前身份没有所需权限",
      message || "账务数据已从当前窗口清除，请联系账本所有者调整权限。",
      {managerAction: true}
    );
    return;
  }
  const lastSync = state.payload?.generated_at ? timeText(state.payload.generated_at) : "";
  const lastSyncSuffix = lastSync ? ` · 最后同步 ${lastSync}` : "";
  setConnection(
    "checking",
    state.payload ? `同步失败 · 显示上次内容${lastSyncSuffix}` : "同步暂不可用"
  );
  setWorkspaceAvailability(state.principalReady);
  if (state.payload) {
    $("syncNote").textContent = `同步失败 · 正在显示上次可信内容${lastSyncSuffix}`;
    clearStatusPanel();
    return;
  }
  setStatusPanel(
    "暂时无法同步",
    message || "暂时无法取得账务数据，请稍后重试。",
    {managerAction}
  );
}

function renderWorkspaceChrome(workspace) {
  const meta = workspaceMeta[workspace];
  workspaceControls.forEach((control) => {
    const current = control.dataset.workspace === workspace;
    control.classList.toggle("is-current", current);
    if (current) control.setAttribute("aria-current", "page");
    else control.removeAttribute("aria-current");
  });
  $("workspaceKicker").textContent = `${meta.index} · ${meta.kicker}`;
  $("workspaceTitle").textContent = meta.title;
  $("workspaceSummary").textContent = meta.summary;
  document.title = `小票夹 · ${meta.title}`;
  const nextHash = `#${workspace}`;
  if (window.location.hash !== nextHash) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${nextHash}`);
  }
  setWorkspaceView(workspace);
  renderColumnHeaders(workspace);
}

function setWorkspaceView(workspace) {
  $("tableView").hidden = !["inbox", "transactions", "obligations"].includes(workspace);
  $("planView").hidden = workspace !== "plans";
  $("insightView").hidden = workspace !== "insights";
}

function renderColumnHeaders(workspace) {
  const columns = tableWorkspaceColumns[workspace];
  if (!columns) return;
  columns.forEach((column, index) => {
    $(`columnHeader${index + 1}`).textContent = column.label;
  });
}

function statusTone(status) {
  if (["attention", "pending", "open", "near_limit"].includes(status)) return "attention";
  if (["voided", "error", "blocked", "over_limit"].includes(status)) return "blocked";
  return "normal";
}

function amountText(row) {
  if (row.amount_minor !== null && row.amount_minor !== undefined && row.currency_code) {
    const zeroFraction = ["JPY", "KRW"].includes(String(row.currency_code).toUpperCase());
    const divisor = zeroFraction ? 1 : 100;
    try {
      return new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency: row.currency_code,
        minimumFractionDigits: zeroFraction ? 0 : 2,
        maximumFractionDigits: zeroFraction ? 0 : 2
      }).format(row.amount_minor / divisor);
    } catch (_error) {
      return `${row.currency_code} ${row.amount_minor}`;
    }
  }
  return row.value_text || "—";
}

function timeText(value, precision = "") {
  if (!value) return "—";
  const dateOnly = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (precision === "date" || dateOnly) {
    if (!dateOnly) return String(value);
    return `${Number(dateOnly[2])}月${Number(dateOnly[3])}日`;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(parsed);
}

function editableAmountText(edit) {
  if (edit.amount_minor === null || edit.amount_minor === undefined) return "";
  const digits = Number(edit.minor_unit_digits || 0);
  const amountMinor = Number(edit.amount_minor);
  if (!Number.isSafeInteger(amountMinor)) return "";
  const absoluteMinor = BigInt(Math.abs(amountMinor));
  const divisor = 10n ** BigInt(digits);
  const whole = absoluteMinor / divisor;
  const fraction = absoluteMinor % divisor;
  const sign = amountMinor < 0 ? "-" : "";
  if (digits === 0) return `${sign}${whole}`;
  return `${sign}${whole}.${String(fraction).padStart(digits, "0")}`;
}

function editableCurrencyLabel(edit) {
  const code = String(edit.currency_code || "CNY").toUpperCase();
  const symbol = String(edit.currency_symbol || code);
  return `金额（${code} · ${symbol}）`;
}

function roleText(role) {
  return roleLabels[role] || "成员";
}

function rowSearchText(row) {
  return [
    row.title,
    row.subtitle,
    row.status_label,
    row.value_text,
    ...(row.fields || []).flatMap((field) => [field.label, field.value])
  ].filter(Boolean).join(" ").toLocaleLowerCase("zh-CN");
}

function updateVisibleRows() {
  const query = $("searchInput").value.trim().toLocaleLowerCase("zh-CN");
  state.visibleRows = query
    ? state.rows.filter((row) => rowSearchText(row).includes(query))
    : [...state.rows];
  if (!state.visibleRows.some((row) => row.key === state.selectedKey)) {
    state.selectedKey = state.visibleRows[0]?.key || "";
  }
  renderTable();
}

function makeCell(text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function selectedRowNode() {
  return recordNodes().find((rowNode) => rowNode.dataset.key === state.selectedKey) || null;
}

function recordNodes() {
  return [...document.querySelectorAll(".data-row")]
    .filter((rowNode) => rowNode.getClientRects().length > 0);
}

function inspectorFocusableElements() {
  return [...$("inspector").querySelectorAll(inspectorFocusableSelector)]
    .filter((element) => element.getClientRects().length > 0);
}

function syncInspectorPresentation() {
  const compactWindow = compactInspectorMedia.matches;
  const drawerOpen = compactWindow && state.inspectorOpen && Boolean(state.selectedKey);
  $("inspector").dataset.open = String(!compactWindow || drawerOpen);
  $("primaryRail").inert = drawerOpen;
  $("dataStage").inert = drawerOpen;
  if (compactWindow) {
    $("inspector").setAttribute("role", "dialog");
    $("inspector").setAttribute("aria-modal", "true");
    $("inspector").setAttribute("aria-hidden", String(!drawerOpen));
    return;
  }
  $("inspector").removeAttribute("role");
  $("inspector").removeAttribute("aria-modal");
  $("inspector").removeAttribute("aria-hidden");
}

function openInspector() {
  if (!compactInspectorMedia.matches || !state.selectedKey) return;
  state.inspectorOpen = true;
  syncInspectorPresentation();
  $("inspectorCloseButton").focus();
}

function closeInspector({restoreFocus = true} = {}) {
  const rowNode = restoreFocus ? selectedRowNode() : null;
  state.inspectorOpen = false;
  syncInspectorPresentation();
  if (rowNode) rowNode.focus();
}

function trapInspectorFocus(event) {
  const focusable = inspectorFocusableElements();
  if (focusable.length === 0) {
    event.preventDefault();
    $("inspector").focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function syncRowDisclosureSemantics() {
  recordNodes().forEach((rowNode) => {
    rowNode.setAttribute("aria-controls", "inspector");
    if (compactInspectorMedia.matches) {
      rowNode.setAttribute("aria-haspopup", "dialog");
      rowNode.setAttribute("aria-keyshortcuts", "Enter");
    } else {
      rowNode.removeAttribute("aria-haspopup");
      rowNode.removeAttribute("aria-keyshortcuts");
    }
  });
}

function selectRow(key, {focus = false, scroll = false, openDetails = false} = {}) {
  state.selectedKey = key;
  recordNodes().forEach((rowNode) => {
    const selected = rowNode.dataset.key === key;
    rowNode.setAttribute("aria-selected", String(selected));
    rowNode.tabIndex = selected ? 0 : -1;
    if (selected && focus) rowNode.focus();
    if (selected && scroll) rowNode.scrollIntoView({block: "nearest"});
  });
  renderInspector(state.visibleRows.find((row) => row.key === key) || null);
  if (openDetails) openInspector();
}

function configureRecordNode(node, row) {
  node.classList.add("data-row");
  node.dataset.key = row.key;
  node.setAttribute("aria-selected", String(row.key === state.selectedKey));
  node.setAttribute("aria-controls", "inspector");
  node.tabIndex = row.key === state.selectedKey ? 0 : -1;
  node.addEventListener("click", () => selectRow(row.key, {openDetails: true}));
  node.addEventListener("focus", () => selectRow(row.key));
  return node;
}

function makeStatusCell(row, text) {
  const statusCell = document.createElement("td");
  const pill = document.createElement("span");
  pill.className = "status-pill";
  pill.dataset.tone = statusTone(row.status);
  pill.textContent = text;
  pill.title = text;
  statusCell.append(pill);
  return statusCell;
}

function renderDataGrid() {
  const columns = tableWorkspaceColumns[state.workspace];
  const fragment = document.createDocumentFragment();
  state.visibleRows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const text = String(column.value(row) ?? "—");
      tr.append(column.status ? makeStatusCell(row, text) : makeCell(text));
    });
    fragment.append(configureRecordNode(tr, row));
  });
  $("rowTableBody").replaceChildren(fragment);
}

function makeWorkspaceRecord(row) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "workspace-record";
  const copy = document.createElement("span");
  copy.className = "record-copy";
  const title = document.createElement("span");
  title.className = "record-title";
  title.textContent = row.title || "—";
  const meta = document.createElement("span");
  meta.className = "record-meta";
  const occurred = timeText(row.occurred_at, row.occurred_precision);
  meta.textContent = [row.subtitle, occurred === "—" ? "" : occurred]
    .filter(Boolean)
    .join(" · ") || "暂无补充说明";
  copy.append(title, meta);
  const side = document.createElement("span");
  side.className = "record-side";
  const value = document.createElement("span");
  value.className = "record-value";
  value.textContent = amountText(row);
  const recordState = document.createElement("span");
  recordState.className = "record-state";
  recordState.textContent = row.status_label || row.status || "—";
  side.append(value, recordState);
  button.append(copy, side);
  return configureRecordNode(button, row);
}

function renderPlanGroups() {
  const fragment = document.createDocumentFragment();
  Object.entries(planGroupMeta).forEach(([kind, meta]) => {
    const rows = state.visibleRows.filter((row) => row.kind === kind);
    const section = document.createElement("section");
    section.className = "plan-group";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const title = document.createElement("h2");
    title.id = `planGroup-${kind}`;
    title.textContent = meta.title;
    const count = document.createElement("span");
    count.textContent = `${rows.length} 项`;
    heading.append(title, count);
    section.setAttribute("aria-labelledby", title.id);
    const detail = document.createElement("p");
    detail.className = "group-description";
    detail.textContent = meta.detail;
    const list = document.createElement("div");
    list.className = "record-list";
    if (rows.length) {
      rows.forEach((row) => list.append(makeWorkspaceRecord(row)));
    } else {
      const empty = document.createElement("p");
      empty.className = "section-empty";
      empty.textContent = "当前没有这一类计划。";
      list.append(empty);
    }
    section.append(heading, detail, list);
    fragment.append(section);
  });
  $("planGroups").replaceChildren(fragment);
}

function renderInsightFact(row) {
  const host = $("insightFact");
  host.replaceChildren();
  host.hidden = !row;
  if (!row) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "fact-button";
  const heading = document.createElement("span");
  heading.className = "fact-heading";
  const copy = document.createElement("span");
  const title = document.createElement("span");
  title.id = "insightFactTitle";
  title.className = "fact-title";
  title.textContent = row.title || "本月事实";
  const subtitle = document.createElement("span");
  subtitle.className = "fact-subtitle";
  subtitle.textContent = row.subtitle || "当前账本的已确认事实。";
  copy.append(title, subtitle);
  const value = document.createElement("strong");
  value.className = "fact-value";
  value.textContent = amountText(row);
  heading.append(copy, value);
  const fields = document.createElement("span");
  fields.className = "fact-fields";
  (row.fields || []).forEach((field) => {
    const item = document.createElement("span");
    item.className = "fact-field";
    const label = document.createElement("span");
    label.textContent = field.label;
    const fieldValue = document.createElement("strong");
    fieldValue.textContent = field.value;
    item.append(label, fieldValue);
    fields.append(item);
  });
  button.append(heading, fields);
  host.append(configureRecordNode(button, row));
}

function renderInsightRecords(host, rows, emptyCopy) {
  const fragment = document.createDocumentFragment();
  if (rows.length) {
    rows.forEach((row) => fragment.append(makeWorkspaceRecord(row)));
  } else {
    const empty = document.createElement("p");
    empty.className = "section-empty";
    empty.textContent = emptyCopy;
    fragment.append(empty);
  }
  host.replaceChildren(fragment);
}

function renderInsights() {
  const report = state.visibleRows.find((row) => row.kind === "report_summary") || null;
  const metrics = state.visibleRows.filter((row) => row.kind === "quality_metric");
  const attention = metrics.filter((row) => statusTone(row.status) === "attention");
  const healthy = metrics.filter((row) => statusTone(row.status) !== "attention");
  renderInsightFact(report);
  renderInsightRecords($("attentionRecords"), attention, "当前没有需要优先处理的数据问题。");
  renderInsightRecords($("qualityRecords"), healthy, "没有其它可展示的数据质量项。");
  $("attentionCount").textContent = `${attention.length} 项`;
  $("qualityCount").textContent = `${healthy.length} 项`;
}

function renderTable() {
  $("rowTableBody").replaceChildren();
  $("planGroups").replaceChildren();
  $("insightFact").replaceChildren();
  $("attentionRecords").replaceChildren();
  $("qualityRecords").replaceChildren();
  setWorkspaceView(state.workspace);
  if (tableWorkspaceColumns[state.workspace]) renderDataGrid();
  if (state.workspace === "plans") renderPlanGroups();
  if (state.workspace === "insights") renderInsights();
  syncRowDisclosureSemantics();
  const total = state.payload?.total_count ?? state.rows.length;
  const suffix = state.payload?.truncated ? `（显示前 ${state.rows.length} 项）` : "";
  $("rowCount").textContent = `${state.visibleRows.length} / ${total} 项${suffix}`;
  const empty = state.visibleRows.length === 0;
  $("emptyPanel").hidden = !empty || !$("statusPanel").hidden;
  if (empty) {
    const filtered = Boolean($("searchInput").value.trim());
    $("emptyTitle").textContent = filtered ? "没有匹配结果" : (state.payload?.empty_title || "当前没有数据");
      $("emptyDetail").textContent = filtered
        ? "清除筛选条件查看当前业务域全部记录。"
        : (state.payload?.empty_detail || "当前没有需要显示的记录。");
  }
  renderInspector(state.visibleRows.find((row) => row.key === state.selectedKey) || null);
}

function renderInspector(row) {
  const command = $("inboxCommand");
  $("commandFeedback").textContent = "";
  $("commandFeedback").dataset.tone = "";
  if (!row) {
    closeInspector({restoreFocus: false});
    $("inspectorKicker").textContent = "详情 · 尚未选择";
    $("inspectorTitle").textContent = "选择一项";
    $("inspectorSubtitle").textContent = "选择一项后，这里会显示详细信息。";
    $("inspectorValue").textContent = "—";
    $("fieldList").replaceChildren();
    $("commandAmountLabel").textContent = "金额";
    command.hidden = true;
    $("inspectorFooter").textContent = "选择一项查看详情；待整理记录可直接处理。";
    return;
  }
  $("inspectorKicker").textContent = `${workspaceMeta[state.workspace].title} · ${row.status_label || row.status}`;
  $("inspectorTitle").textContent = row.title || "—";
  $("inspectorSubtitle").textContent = row.subtitle || "无补充说明";
  $("inspectorValue").textContent = amountText(row);
  const fragment = document.createDocumentFragment();
  (row.fields || []).forEach((field) => {
    const wrapper = document.createElement("div");
    wrapper.className = "field-row";
    const term = document.createElement("dt");
    term.textContent = field.label;
    const detail = document.createElement("dd");
    detail.textContent = field.value;
    wrapper.append(term, detail);
    fragment.append(wrapper);
  });
  $("fieldList").replaceChildren(fragment);
  const capabilities = new Set(Array.isArray(row.capabilities) ? row.capabilities : []);
  const editable = state.workspace === "inbox" && row.edit && capabilities.size > 0;
  command.hidden = !editable;
  if (editable) {
    $("commandAmountLabel").textContent = editableCurrencyLabel(row.edit);
    $("commandAmount").value = editableAmountText(row.edit);
    $("commandMerchant").value = row.edit.merchant || "";
    $("commandCategory").value = row.edit.category || "";
    $("saveCommand").hidden = !capabilities.has("save");
    $("confirmCommand").hidden = !capabilities.has("confirm");
    $("ignoreCommand").hidden = !capabilities.has("ignore");
    $("inspectorFooter").textContent = "可先修改内容，再保存、确认入账或忽略。";
  } else if (state.workspace === "inbox" && row.edit) {
    $("commandAmountLabel").textContent = editableCurrencyLabel(row.edit);
    $("inspectorFooter").textContent = "当前账本为只读，你仍可查看这项记录。";
  } else {
    $("commandAmountLabel").textContent = "金额";
    $("inspectorFooter").textContent = "选择其他记录继续查看详情。";
  }
  if (state.commandNotice && editable) {
    $("commandFeedback").textContent = state.commandNotice;
    $("commandFeedback").dataset.tone = "success";
    state.commandNotice = "";
  }
  setCommandBusy(state.commandBusy);
}

function setCommandBusy(busy) {
  state.commandBusy = busy;
  ["commandAmount", "commandMerchant", "commandCategory", "saveCommand", "confirmCommand", "ignoreCommand"]
    .forEach((id) => { $(id).disabled = busy; });
}

function requestConfirmation({title, detail, actionLabel, tone = "danger"}) {
  const dialog = $("confirmDialog");
  if (typeof dialog.showModal !== "function") {
    return Promise.resolve(window.confirm(`${title}\n\n${detail}`));
  }
  if (dialog.open) dialog.close("cancel");
  $("confirmTitle").textContent = title;
  $("confirmDetail").textContent = detail;
  $("confirmActionButton").textContent = actionLabel;
  $("confirmActionButton").dataset.tone = tone;
  dialog.returnValue = "cancel";
  return new Promise((resolve) => {
    state.confirmationResolve = resolve;
    dialog.showModal();
    $("confirmCancelButton").focus();
  });
}

function selectedInboxRow() {
  const row = state.visibleRows.find((candidate) => candidate.key === state.selectedKey);
  if (
    state.workspace !== "inbox"
    || !row
    || row.kind !== "expense"
    || !row.key.startsWith("expense:")
    || !row.edit
  ) return null;
  return row;
}

function commandEditFields(row) {
  const amount = $("commandAmount").value.trim();
  const digits = Number(row.edit?.minor_unit_digits || 0);
  const amountPattern = digits === 0
    ? /^\d+$/
    : new RegExp(`^\\d+(?:\\.\\d{1,${digits}})?$`);
  if (!amountPattern.test(amount)) {
    const precision = digits === 0 ? "不含小数" : `最多 ${digits} 位小数`;
    throw new Error(`请填写不小于 0、${precision}的金额。`);
  }
  const [whole, fraction = ""] = amount.split(".");
  const paddedFraction = fraction.padEnd(digits, "0");
  const amountMinorBigInt = (BigInt(whole) * (10n ** BigInt(digits)))
    + BigInt(paddedFraction || "0");
  if (amountMinorBigInt > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("金额超出可处理范围。");
  }
  const amountMinor = Number(amountMinorBigInt);
  const fields = {};
  if (amountMinor !== row.edit.original_amount_minor) {
    Object.assign(fields, {
      original_amount_minor: amountMinor,
      original_currency_code: row.edit.original_currency_code,
      home_amount_minor: row.edit.home_amount_minor,
      home_currency_code: row.edit.home_currency_code,
      exchange_rate_to_home: row.edit.exchange_rate_to_home,
      exchange_rate_date: row.edit.exchange_rate_date,
      exchange_rate_source: row.edit.exchange_rate_source,
      fx_status: row.edit.fx_status
    });
  }
  const merchant = $("commandMerchant").value.trim();
  if (merchant !== (row.edit.merchant || "")) fields.merchant = merchant;
  const category = $("commandCategory").value.trim();
  if (category !== (row.edit.category || "")) fields.category = category;
  return fields;
}

async function runInboxCommand(action) {
  if (state.commandBusy) return;
  const row = selectedInboxRow();
  if (!row || !(row.capabilities || []).includes(action)) return;
  if (action === "ignore") {
    const confirmed = await requestConfirmation({
      title: "忽略这条收件？",
      detail: `${row.title || "当前收件"} · ${amountText(row)}。它会从待整理队列移出，不会改动已确认流水。`,
      actionLabel: "确认忽略"
    });
    if (!confirmed) return;
  }
  let body = {
    action,
    expected_row_version: row.edit.expected_row_version
  };
  try {
    if (action !== "ignore") {
      const editFields = commandEditFields(row);
      if (action === "save" && Object.keys(editFields).length === 0) {
        throw new Error("没有需要保存的更改。");
      }
      body = {...body, ...editFields};
    }
  } catch (error) {
    $("commandFeedback").textContent = error instanceof Error ? error.message : "请检查输入内容。";
    $("commandFeedback").dataset.tone = "error";
    return;
  }
  const publicId = row.key.slice("expense:".length);
  const signature = JSON.stringify({publicId, ledgerId: state.ledgerId, body});
  if (!state.pendingCommand || state.pendingCommand.signature !== signature) {
    state.pendingCommand = {signature, key: freshIdempotencyKey()};
  }
  setCommandBusy(true);
  $("commandFeedback").textContent = "正在保存…";
  $("commandFeedback").dataset.tone = "";
  const params = new URLSearchParams();
  if (state.ledgerId) params.set("ledger_id", state.ledgerId);
  const query = params.toString();
  try {
    const response = await fetch(
      `/api/product/inbox/expenses/${encodeURIComponent(publicId)}/commands${query ? `?${query}` : ""}`,
      {
        method: "POST",
        headers: {
          ...requestHeaders(),
          "Content-Type": "application/json",
          "Idempotency-Key": state.pendingCommand.key
        },
        body: JSON.stringify(body)
      }
    );
    const payload = await response.json().catch(() => ({}));
    const preserveRetryKey = response.status >= 500
      || payload.error === "idempotency_key_in_progress";
    if (!preserveRetryKey) state.pendingCommand = null;
    if (!response.ok) {
      if (payload.error === "state_conflict") {
        state.commandNotice = "内容已在其它端修改，已刷新为最新版本。";
        setCommandBusy(false);
        await loadWorkspace({preserveSelection: true});
        return;
      }
      if (response.status === 401 || response.status === 403) {
        failClosedProductState(
          payload.message || "当前身份无法继续访问此账本。",
          {status: response.status, error: payload.error || ""}
        );
        return;
      }
      const failure = new Error(payload.message || "收件操作失败，请稍后重试。");
      failure.status = response.status;
      failure.code = payload.error || "";
      throw failure;
    }
    state.pendingCommand = null;
    state.commandNotice = payload.message || "收件操作已完成。";
    setCommandBusy(false);
    await loadWorkspace({preserveSelection: action === "save"});
  } catch (error) {
    failClosedProductState(
      error instanceof Error ? error.message : "收件操作失败，请稍后重试。",
      {
        status: Number(error?.status || 0),
        error: String(error?.code || "")
      }
    );
  } finally {
    setCommandBusy(false);
  }
}

function renderLedgerOptions(payload) {
  const options = (payload.ledgers || []).map((ledger) => {
    const option = document.createElement("option");
    option.value = ledger.ledger_id;
    option.textContent = `${ledger.name} · ${roleText(ledger.role)}`;
    option.selected = ledger.ledger_id === payload.ledger_id;
    return option;
  });
  $("ledgerSelect").replaceChildren(...options);
  state.ledgerId = payload.ledger_id || "";
  $("ledgerSelect").disabled = state.loading || options.length < 2;
}

function renderPayload(payload, {preferredKey = ""} = {}) {
  state.payload = payload;
  state.rows = Array.isArray(payload.rows) ? payload.rows : [];
  state.selectedKey = state.rows.some((row) => row.key === preferredKey)
    ? preferredKey
    : (state.rows[0]?.key || "");
  renderLedgerOptions(payload);
  $("roleNote").textContent = `${payload.ledger_name} · ${roleText(payload.role)}`;
  const generated = timeText(payload.generated_at);
  $("syncNote").textContent = `最近同步 · ${generated}`;
  if (state.commandNotice) {
    $("syncNote").textContent = state.commandNotice;
  }
  clearStatusPanel();
  setConnection("ready", "已同步");
  updateVisibleRows();
}

async function loadWorkspace({preserveSelection = true} = {}) {
  if (!state.productAvailable || state.loading || state.commandBusy) return;
  const requestedLedger = state.ledgerId;
  const requestedWorkspace = state.workspace;
  const requestedSelection = preserveSelection ? state.selectedKey : "";
  state.loading = true;
  const serial = ++state.requestSerial;
  setWorkspaceAvailability(true);
  setCommandBusy(true);
  $("dataStage").setAttribute("aria-busy", "true");
  $("refreshButton").textContent = "刷新中";
  $("syncNote").textContent = "正在同步…";
  setConnection("checking", "正在同步");
  const params = new URLSearchParams();
  if (requestedLedger) params.set("ledger_id", requestedLedger);
  const query = params.toString();
  try {
    const response = await fetch(
      `/api/product/${requestedWorkspace}${query ? `?${query}` : ""}`,
      {headers: requestHeaders()}
    );
    const payload = await response.json().catch(() => ({}));
    if (serial !== state.requestSerial) return;
    if (!response.ok) {
      failClosedProductState(
        payload.message || "账务数据暂时不可用，请稍后刷新。",
        {status: response.status, error: payload.error || "", managerAction: true}
      );
      return;
    }
    const preferredKey = preserveSelection ? state.selectedKey : requestedSelection;
    renderPayload(payload, {preferredKey});
  } catch (error) {
    if (serial !== state.requestSerial) return;
    failClosedProductState(
      error instanceof Error
        ? error.message
        : "请稍后刷新，或进入系统管理检查服务。",
      {managerAction: true}
    );
  } finally {
    if (serial === state.requestSerial) {
      state.loading = false;
      setCommandBusy(false);
      $("dataStage").setAttribute("aria-busy", "false");
      $("refreshButton").textContent = "刷新";
      setWorkspaceAvailability(state.productAvailable);
    }
  }
}

function switchWorkspace(workspace, {focusRow = false} = {}) {
  if (!workspaceOrder.includes(workspace)) return;
  const activeLedger = state.ledgerId;
  state.workspace = workspace;
  clearProductData();
  state.ledgerId = activeLedger;
  renderWorkspaceChrome(workspace);
  loadWorkspace({preserveSelection: false}).then(() => {
    if (focusRow && state.selectedKey) selectRow(state.selectedKey, {focus: true});
  });
}

async function refreshProductPrincipal() {
  if (state.principalLoading) return;
  state.principalLoading = true;
  try {
    const response = await fetch(
      "/api/product/session",
      {headers: requestHeaders()}
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      failClosedProductState(
        payload.message || "无法读取桌面绑定状态。",
        {status: response.status, error: payload.error || "", managerAction: true}
      );
      return;
    }
    if (payload.configured !== true) {
      failClosedProductState(
        "请在系统管理中生成 8 位绑定码，然后在此完成连接。",
        {status: 401, error: "product_principal_required"}
      );
      return;
    }
    const becameAvailable = !state.productAvailable;
    state.principalReady = true;
    setWorkspaceAvailability(true);
    setConnection("ready", "桌面账本已绑定");
    $("unpairButton").hidden = false;
    if (becameAvailable || state.payload === null) {
      await loadWorkspace({preserveSelection: true});
    }
  } catch (error) {
    failClosedProductState(
      error instanceof Error ? error.message : "无法读取桌面绑定状态。",
      {managerAction: true}
    );
  } finally {
    state.principalLoading = false;
  }
}

async function pairProductPrincipal(event) {
  event.preventDefault();
  const pairingCode = $("pairingCode").value.trim();
  if (!/^\d{8}$/.test(pairingCode)) {
    $("pairingFeedback").textContent = "请输入 8 位数字绑定码。";
    return;
  }
  $("pairingFeedback").textContent = "正在安全连接账本…";
  try {
    const response = await fetch("/api/product/pair", {
      method: "POST",
      headers: {
        ...requestHeaders(),
        "Content-Type": "application/json"
      },
      body: JSON.stringify({pairing_code: pairingCode})
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      failClosedProductState(
        payload.message || "绑定失败，请检查绑定码后重试。",
        {status: response.status, error: payload.error || "", managerAction: true}
      );
      return;
    }
    state.principalReady = true;
    $("pairingCode").value = "";
    clearStatusPanel();
    setWorkspaceAvailability(true);
    await loadWorkspace({preserveSelection: false});
  } catch (error) {
    failClosedProductState(
      error instanceof Error ? error.message : "绑定失败，请稍后重试。",
      {managerAction: true}
    );
  }
}

async function unpairProductPrincipal() {
  if (state.loading || state.commandBusy) return;
  const confirmed = await requestConfirmation({
    title: "解除这台电脑的账本绑定？",
    detail: "这会撤销当前桌面会话并清除本机安全凭据，不会删除账本或任何财务记录。",
    actionLabel: "解除绑定"
  });
  if (!confirmed) return;
  clearProductData("正在解除桌面绑定…");
  setWorkspaceAvailability(false);
  try {
    const response = await fetch("/api/product/unpair", {
      method: "POST",
      headers: requestHeaders()
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      failClosedProductState(
        payload.message || "无法解除桌面绑定，请稍后重试。",
        {status: response.status, error: payload.error || "", managerAction: true}
      );
      return;
    }
    state.principalReady = false;
    failClosedProductState(
      "桌面绑定已解除。需要继续使用时，请输入新的 8 位绑定码。",
      {status: 401, error: "product_principal_required"}
    );
  } catch (error) {
    failClosedProductState(
      error instanceof Error ? error.message : "无法解除桌面绑定，请稍后重试。",
      {managerAction: true}
    );
  }
}

async function switchProductLedger(targetLedger) {
  if (
    state.loading
    || state.commandBusy
    || !state.principalReady
    || !targetLedger
    || targetLedger === state.ledgerId
  ) return;
  clearProductData("正在安全切换账本…");
  setWorkspaceAvailability(false);
  try {
    const response = await fetch("/api/product/ledger/switch", {
      method: "POST",
      headers: {
        ...requestHeaders(),
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ledger_id: targetLedger})
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      failClosedProductState(
        payload.message || "无法切换到所选账本。",
        {status: response.status, error: payload.error || "", managerAction: true}
      );
      return;
    }
    state.principalReady = true;
    setWorkspaceAvailability(true);
    await loadWorkspace({preserveSelection: false});
  } catch (error) {
    failClosedProductState(
      error instanceof Error ? error.message : "无法切换到所选账本。",
      {managerAction: true}
    );
  }
}

function render(status) {
  if (status.manager_shutdown_requested) {
    clearProductData("管理器正在关闭");
    setWorkspaceAvailability(false);
    setConnection("blocked", "管理器正在关闭");
    setStatusPanel("小票夹正在完成系统维护", "当前窗口会在维护交接完成后关闭。");
    return;
  }
  if (!status.product_available) {
    clearProductData("小票夹服务尚未就绪");
    setWorkspaceAvailability(false);
    const stopped = !status.running || status.health_state === "stopped";
    setConnection("blocked", stopped ? "服务已停止" : "服务尚未就绪");
    setStatusPanel(
      stopped ? "小票夹服务已停止" : "小票夹服务尚未就绪",
      stopped
        ? "进入系统管理启动服务或导出诊断。"
        : "日常业务入口保持关闭，不会显示过期或伪造状态。",
      {managerAction: true}
    );
    return;
  }
  if (!state.principalReady) {
    clearProductData("正在验证桌面账本身份…");
    setWorkspaceAvailability(false);
    refreshProductPrincipal();
    return;
  }
  const becameAvailable = !state.productAvailable;
  setWorkspaceAvailability(true);
  setConnection("ready", "已同步");
  if (becameAvailable || state.payload === null) loadWorkspace({preserveSelection: true});
}

async function refresh() {
  try {
    const response = await fetch("/api/status", {headers: requestHeaders()});
    if (!response.ok) throw new Error("status");
    render(await response.json());
  } catch (_error) {
    failClosedProductState(
      "管理器连接中断；正在显示上次可信内容，请稍后重试。",
      {managerAction: true}
    );
  }
}

workspaceControls.forEach((control) => {
  control.addEventListener("click", () => switchWorkspace(control.dataset.workspace || "inbox"));
});
$("refreshButton").addEventListener("click", () => loadWorkspace({preserveSelection: true}));
$("ledgerSelect").addEventListener("change", () => {
  const targetLedger = $("ledgerSelect").value;
  switchProductLedger(targetLedger);
});
$("pairingForm").addEventListener("submit", pairProductPrincipal);
$("unpairButton").addEventListener("click", unpairProductPrincipal);
$("searchInput").addEventListener("input", updateVisibleRows);
$("inboxCommand").addEventListener("submit", (event) => {
  event.preventDefault();
  runInboxCommand("save");
});
$("confirmCommand").addEventListener("click", () => runInboxCommand("confirm"));
$("ignoreCommand").addEventListener("click", () => runInboxCommand("ignore"));
$("inspectorCloseButton").addEventListener("click", () => closeInspector());
$("confirmDialog").addEventListener("close", () => {
  const resolve = state.confirmationResolve;
  state.confirmationResolve = null;
  const confirmed = $("confirmDialog").returnValue === "confirm";
  delete $("confirmActionButton").dataset.tone;
  if (resolve) resolve(confirmed);
});
$("manageLink").href = managerPath();
$("statusAction").href = managerPath();

document.addEventListener("keydown", (event) => {
  if ($("confirmDialog").open) return;
  if (compactInspectorMedia.matches && state.inspectorOpen) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeInspector();
    } else if (event.key === "Tab") {
      trapInspectorFocus(event);
    }
    return;
  }
  if (
    compactInspectorMedia.matches
    && event.key === "Enter"
    && document.activeElement?.classList.contains("data-row")
  ) {
    event.preventDefault();
    selectRow(document.activeElement.dataset.key, {openDetails: true});
    return;
  }
  if (event.altKey && !event.ctrlKey && !event.metaKey) {
    if (event.key === "0") {
      event.preventDefault();
      $("manageLink").click();
      return;
    }
    const target = workspaceControls.find((control) => control.dataset.shortcut === event.key);
    if (target && !target.disabled) {
      event.preventDefault();
      switchWorkspace(target.dataset.workspace || "inbox", {focusRow: false});
      return;
    }
  }
  const refreshKey = event.key === "F5"
    || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "r");
  if (refreshKey) {
    event.preventDefault();
    loadWorkspace({preserveSelection: true});
    return;
  }
  if (
    event.key === "/"
    && !event.ctrlKey
    && !event.metaKey
    && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)
  ) {
    event.preventDefault();
    $("searchInput").focus();
    return;
  }
  if (event.key === "Escape" && document.activeElement === $("searchInput")) {
    $("searchInput").value = "";
    updateVisibleRows();
    $("searchInput").blur();
    return;
  }
  if (
    ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)
    || !["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)
    || state.visibleRows.length === 0
  ) return;
  event.preventDefault();
  const currentIndex = Math.max(0, state.visibleRows.findIndex((row) => row.key === state.selectedKey));
  let nextIndex = currentIndex;
  if (event.key === "ArrowUp") nextIndex = Math.max(0, currentIndex - 1);
  if (event.key === "ArrowDown") nextIndex = Math.min(state.visibleRows.length - 1, currentIndex + 1);
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = state.visibleRows.length - 1;
  selectRow(state.visibleRows[nextIndex].key, {focus: true, scroll: true});
});

compactInspectorMedia.addEventListener("change", () => {
  const restoreFocus = state.inspectorOpen || $("inspector").contains(document.activeElement);
  closeInspector({restoreFocus});
  syncRowDisclosureSemantics();
});

renderWorkspaceChrome(state.workspace);
syncInspectorPresentation();
refresh();
setInterval(refresh, 5000);
