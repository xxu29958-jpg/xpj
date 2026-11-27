let running = false;
let refreshInFlight = false;
let actionInFlight = false;
let latestStatus = null;
const $ = (id) => document.getElementById(id);
const STATUS_REFRESH_DEADLINE_MS = 2000;
const PUBLIC_CONNECTIVITY_ACTIONS = Object.freeze({
  refresh: {label: "刷新状态", action: "refresh_public_connectivity"},
  full_check: {label: "完整检查", action: "run_full_public_connectivity_check"},
  export_diagnostics: {label: "导出诊断", action: "export_diagnostics"}
});
const PUBLIC_CONNECTIVITY_ACTION_IDS = Object.freeze({
  refresh: "publicConnectivityRefreshAction",
  full_check: "publicConnectivityFullCheckAction",
  export_diagnostics: "publicConnectivityExportAction"
});
const PUBLIC_CONNECTIVITY_OVERALL = Object.freeze({
  unsafe: {label: "存在风险", tone: "unsafe"},
  offline: {label: "连接离线", tone: "degraded"},
  connector_unavailable: {label: "连接器不可用", tone: "degraded"},
  origin_unavailable: {label: "源站不可用", tone: "degraded"},
  public_unavailable: {label: "公网不可用", tone: "degraded"},
  degraded: {label: "连接降级", tone: "degraded"},
  healthy: {label: "已验证", tone: "healthy"},
  unknown: {label: "状态未知", tone: "unknown"}
});

function serviceState(state) {
  const labels = {
    running: "运行中", stopped: "已停止", start_pending: "启动中", stop_pending: "停止中",
    paused: "已暂停", missing: "未安装", unknown: "未知"
  };
  return labels[state] || state || "—";
}

function setOverall(kind, text) {
  const target = $("overallState");
  target.className = `overall-state${kind ? ` is-${kind}` : ""}`;
  $("overallText").textContent = text;
}

function setMessage(id, text) {
  const box = $(id);
  box.classList.toggle("is-visible", Boolean(text));
  $(`${id}Text`).textContent = text || "";
}

function applyPublicConnectivityActionAvailability(value) {
  const available = Boolean(value && value.schema === "ticketbox-public-connectivity-v1");
  const inProgress = available && Boolean(value.in_progress);
  document.querySelectorAll(".public-connectivity-action").forEach((button) => {
    const localProbe = button.dataset.publicConnectivityAction !== "export_diagnostics";
    button.disabled = actionInFlight || !available || (localProbe && inProgress);
  });
}

function publicConnectivityRow(row) {
  const item = document.createElement("div");
  const label = document.createElement("div");
  const value = document.createElement("div");
  item.className = "connectivity-row";
  label.className = "connectivity-row-label";
  value.className = "connectivity-row-value";
  label.textContent = row.label;
  value.textContent = row.text;
  item.append(label, value);
  return item;
}

function publicConnectivityAction([key, config]) {
  const button = document.createElement("button");
  button.type = "button";
  button.id = PUBLIC_CONNECTIVITY_ACTION_IDS[key];
  button.className = "button public-connectivity-action";
  button.dataset.publicConnectivityAction = key;
  button.textContent = config.label;
  button.addEventListener("click", () => act(config.action, button));
  return button;
}

function renderPublicConnectivity(value) {
  const projection = value && value.schema === "ticketbox-public-connectivity-v1"
    ? value
    : {
        overall: "unknown",
        summary: "公网连接状态未知",
        next_step: "刷新本机状态，必要时运行完整公网检查。",
        detail_rows: [],
        supported_actions: [],
        in_progress: false
      };
  const visual = PUBLIC_CONNECTIVITY_OVERALL[projection.overall]
    || PUBLIC_CONNECTIVITY_OVERALL.unknown;
  const card = $("publicConnectivityCard");
  card.dataset.state = visual.tone;
  card.setAttribute("aria-busy", String(Boolean(projection.in_progress)));
  $("publicConnectivityBadge").textContent = visual.label;
  const summary = $("publicConnectivitySummary");
  const nextStep = $("publicConnectivityNextStep");
  summary.textContent = projection.summary || "公网连接状态未知";
  nextStep.textContent = projection.next_step || "刷新本机状态，必要时运行完整公网检查。";
  const rows = Array.isArray(projection.detail_rows) ? projection.detail_rows.slice(0, 12) : [];
  $("publicConnectivityDetails").replaceChildren(...rows.filter((row) => (
    row && typeof row.label === "string" && typeof row.text === "string"
  )).map(publicConnectivityRow));
  const supported = new Set(Array.isArray(projection.supported_actions) ? projection.supported_actions : []);
  const actions = Object.entries(PUBLIC_CONNECTIVITY_ACTIONS)
    .filter(([key]) => supported.has(key))
    .map(publicConnectivityAction);
  $("publicConnectivityActions").replaceChildren(...actions);
  applyPublicConnectivityActionAvailability(projection);
}

function connectorButton(label, action, busy) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button connector-action";
  button.textContent = label;
  button.disabled = actionInFlight || busy;
  button.addEventListener("click", () => act(action, button));
  return button;
}

function renderConnectorControls(status) {
  const connection = status.public_connectivity || {};
  const action = status.connector_action || {};
  const supported = connection.managed_action === "available";
  const busy = action.state === "running";
  const primary = [], maintenance = [];
  if (supported && connection.pending_action) {
    primary.push(connectorButton(connection.pending_can_continue ? "继续上次操作" : "关闭未完成的配置",
      connection.pending_can_continue ? "continue_connector" : "remove_connector", busy));
    if (connection.pending_action !== "remove" && connection.pending_can_continue) {
      maintenance.push(connectorButton("停止并移除本机连接", "remove_connector", busy));
    }
  } else if (supported && !connection.configured) {
    primary.push(connectorButton(connection.public === "unconfigured" ? "设置公网地址" : "设置公网连接",
      connection.public === "unconfigured" ? "open_settings" : "configure_connector", busy));
  } else if (supported) {
    primary.push(connectorButton(connection.desired_enabled ? "暂停公网" : "开启公网",
      connection.desired_enabled ? "pause_connector" : "enable_connector", busy));
    if (connection.desired_enabled && connection.overall !== "healthy") {
      primary.push(connectorButton("重新连接", "reconnect_connector", busy));
    }
    maintenance.push(connectorButton("替换连接凭据", "configure_connector", busy),
      connectorButton("移除本机连接", "remove_connector", busy));
  }
  $("connectorPrimaryActions").replaceChildren(...primary);
  $("connectorMaintenanceActions").replaceChildren(...maintenance);
  $("connectorControlHelp").hidden = !supported;
  $("connectorActionNotice").textContent = action.message || "";
  $("connectorActionNotice").hidden = !action.message;
  if (busy) $("publicConnectivityCard").setAttribute("aria-busy", "true");
  if (connection.code === "connector_paused") $("publicConnectivityBadge").textContent = "已暂停";
}

function applyActionAvailability(s) {
  const hasStatus = Boolean(s);
  const isRunning = hasStatus && Boolean(s.running);
  const backendReady = isRunning && Boolean(s.health);
  const productAvailable = backendReady
    && s.runtime_access_state === "available"
    && s.owner_state === "configured";
  const serviceControls = hasStatus && Boolean(s.service_controls_available);
  $("primaryAction").hidden = !serviceControls;
  $("restartAction").hidden = !serviceControls;
  $("primaryAction").disabled = actionInFlight || !serviceControls;
  $("restartAction").disabled = actionInFlight || !serviceControls || !isRunning;
  document.querySelectorAll(".owner-action").forEach((button) => {
    button.disabled = actionInFlight || !productAvailable;
  });
  document.querySelectorAll(".connector-action").forEach((button) => {
    button.disabled = actionInFlight || !productAvailable || s.connector_action?.state === "running";
  });
  // Runtime health cannot authorize product navigation before the
  // current user's WinCred-backed product session has been read.
  $("importExportAction").disabled = actionInFlight
    || !productAvailable
    || !Boolean(productSession && productSession.configured);
  $("iphoneAction").disabled = actionInFlight || !productAvailable || s.iphone_upload_state !== "configured_unverified";
  $("diagnosticExportAction").disabled = actionInFlight;
  $("serviceDiagnosticAction").disabled = actionInFlight;
  applyDesktopPairingAvailability();
  applyPublicConnectivityActionAvailability(hasStatus ? s.public_connectivity : null);
  document.querySelector("main").setAttribute("aria-busy", String(actionInFlight));
}

function render(s) {
  latestStatus = s;
  if (s.manager_shutdown_requested) {
    actionInFlight = true;
    setOverall("warn", "管理器正在交接");
    setMessage("controlError", "安装维护即将开始，管理器会关闭，服务可能暂时不可用。");
    applyActionAvailability(s);
    setTimeout(() => window.close(), 50);
    return;
  }
  running = Boolean(s.running);
  const backendReady = running && Boolean(s.health);
  const pending = running && s.health_state === "pending";
  const mismatch = running && s.health_state === "mismatch";
  const runtimeRepairRequired = backendReady && s.runtime_access_state === "repair_required";
  const ownerRecoveryRequired = backendReady && s.owner_state === "recovery_required";
  const productAvailable = backendReady && !runtimeRepairRequired && !ownerRecoveryRequired;
  const serviceFault = s.runtime_mode === "installed" && (
    ["missing", "unknown"].includes(s.backend_service_state)
    || ["missing", "unknown"].includes(s.database_service_state)
  );
  const androidConfigured = productAvailable && s.android_binding_state === "configured_unverified";
  const iphoneConfigured = productAvailable && s.iphone_upload_state === "configured_unverified";

  if (serviceFault) {
    setOverall("error", "需要处理");
    $("serviceTitle").textContent = "小票夹需要修复";
    $("serviceDetail").textContent = "暂时无法确认小票夹状态，请先导出诊断包，再使用可信安装包手动修复。";
  } else if (!running) {
    setOverall("", "已停止");
    $("serviceTitle").textContent = "小票夹已停止";
    $("serviceDetail").textContent = "启动后可以继续使用电脑端管理功能。";
  } else if (runtimeRepairRequired) {
    setOverall("error", "需要修复安装");
    $("serviceTitle").textContent = "安装维护尚未完成";
    $("serviceDetail").textContent = "请先导出诊断包，再关闭管理器并重新运行可信安装包。";
  } else if (ownerRecoveryRequired) {
    setOverall("warn", "需要恢复身份");
    $("serviceTitle").textContent = "缺少可用拥有者身份";
    $("serviceDetail").textContent = "当前管理器不能自动重建身份，请先导出诊断包。";
  } else if (backendReady) {
    setOverall("ok", "运行正常");
    $("serviceTitle").textContent = "小票夹正在运行";
    $("serviceDetail").textContent = androidConfigured && iphoneConfigured
      ? "电脑端运行正常；手机入口已配置，仍需在手机上完成连接验证。"
      : "电脑端运行正常；手机连接尚未配置。";
  } else if (pending) {
    setOverall("warn", "正在启动");
    $("serviceTitle").textContent = "小票夹正在准备";
    $("serviceDetail").textContent = "数据库与服务正在完成启动。";
  } else {
    setOverall("error", mismatch ? "身份不匹配" : "需要处理");
    $("serviceTitle").textContent = mismatch ? "安装身份校验失败" : "小票夹没有正常响应";
    $("serviceDetail").textContent = s.health_detail || "请打开系统体检或导出诊断包。";
  }

  // When the service card asks for a diagnostic bundle first, the same export sits right under it.
  $("serviceDiagnosticAction").hidden = !(serviceFault || runtimeRepairRequired || ownerRecoveryRequired
    || (running && !backendReady && !pending));

  const primary = $("primaryAction");
  primary.dataset.action = running ? "stop" : "start";
  primary.querySelector(".icon use").setAttribute("href", running ? "#manager-icon-square" : "#manager-icon-play");
  primary.querySelector(".icon").classList.remove("spinner");
  primary.querySelector("span:last-child").textContent = running ? "停止" : "启动";
  primary.classList.toggle("button-danger", running);
  $("runtimeLabel").textContent = s.runtime_mode === "installed" ? "本机安装" : "开发环境 · 源码运行";

  $("connectState").textContent = runtimeRepairRequired
    ? "安装修复完成后才能连接手机。"
    : (ownerRecoveryRequired
      ? "拥有者身份恢复后才能连接手机。"
      : (!backendReady
        ? "服务正常后才能检查手机连接配置。"
    : (androidConfigured && iphoneConfigured
      ? "手机入口已配置，连接结果以手机实测为准。"
      : "当前仅本机可用，请先在设置中配置手机入口。")));
  $("protectState").textContent = s.runtime_mode === "installed"
    ? "导出流水或含历史、关系与原件的账本包，留存业务副本。"
    : "开发环境也可导出流水与完整账本包。冷备工具仅适用于正式安装。";
  $("diagnosticState").textContent = s.diagnostic_bundle_file ? `最近导出：${s.diagnostic_bundle_file}` : "导出包不包含令牌、账本内容或原始日志。";
  renderPublicConnectivity(s.public_connectivity);
  renderConnectorControls(s);

  $("backendService").textContent = serviceState(s.backend_service_state);
  $("databaseService").textContent = serviceState(s.database_service_state);
  $("lan").textContent = s.lan || "—";
  $("versionLabel").textContent = s.version ? `小票夹 ${s.version}` : "小票夹 Desktop Manager";
  setMessage("controlError", s.control_error);
  setMessage("actionNotice", s.action_notice);

  const log = $("log");
  log.replaceChildren(...(s.log || []).map((line) => {
    const row = document.createElement("div");
    row.textContent = line;
    return row;
  }));
  applyActionAvailability(s);
}

let productSession = null;
let productLedgers = [];
let productSessionReadFailed = false;
let productLedgersReadFailed = false;
let productBusy = false;
let ledgerSelectionDirty = false;
// Ledger memberships can change outside this window; re-read the list on
// a slow cadence (every 12th 2.5s tick ≈ 30s), never every tick.
const PRODUCT_LEDGER_REFRESH_TICKS = 12;
let productLedgerRefreshTick = 0;

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

const PRODUCT_ROLES = new Set(["owner", "member", "viewer"]);

function isProductRole(value) {
  return typeof value === "string" && PRODUCT_ROLES.has(value);
}

function isProductSessionPayload(payload) {
  if (!isPlainObject(payload) || typeof payload.configured !== "boolean") return false;
  if (!payload.configured) return payload.pairing_recovery === undefined
    || payload.pairing_recovery === "original_code_required";
  return ["account_name", "ledger_id", "ledger_name", "device_name"]
    .every((key) => isNonEmptyText(payload[key]))
    && isProductRole(payload.role)
    && (payload.expires_at === null || typeof payload.expires_at === "string");
}

function isProductLedgersPayload(payload) {
  return isPlainObject(payload)
    && Array.isArray(payload.ledgers)
    && payload.ledgers.every((row) => isPlainObject(row)
      && isNonEmptyText(row.ledger_id)
      && isNonEmptyText(row.name)
      && isProductRole(row.role)
      && typeof row.is_default === "boolean"
      && typeof row.is_current === "boolean");
}

async function productFetch(path, options = {}) {
  const headers = {"X-Control-Token": window.CONTROL_TOKEN};
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers});
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    // A received status remains useful for error handling, but a malformed
    // body is never promoted to a successful product projection.
  }
  if (!response.ok) {
    const error = new Error(isPlainObject(payload) && isNonEmptyText(payload.message)
      ? payload.message
      : "product");
    error.payload = payload;
    throw error;
  }
  if (!isPlainObject(payload)) throw new Error("product");
  return payload;
}

function applyDesktopPairingAvailability() {
  const disabled = actionInFlight || productBusy
    || !Boolean(latestStatus && latestStatus.product_available)
    || !productSession || productSessionReadFailed || productLedgersReadFailed
    || productSession.pairing_recovery === "original_code_required";
  for (const id of ["desktopPairingCodeAction", "androidAction"]) $(id).disabled = disabled;
}

function renderProductLayout(connecting) {
  $("managerTitle").textContent = connecting ? "连接这台电脑" : "小票夹管理器";
  $("managerDescription").textContent = connecting
    ? "连接之后，沿用你的账本与访问身份。" : "本机服务与桌面账本";
  $("connectionHelp").hidden = !connecting;
  $("productIdentityHint").hidden = !connecting;
  $("productEyebrow").hidden = connecting;
  // Move the existing projections only when the task changes. Their state,
  // action handlers and open disclosures survive regular status refreshes.
  const runtimeParent = connecting ? $("connectionRuntimeHelp") : $("serviceOverview");
  if ($("runtimeCard").parentElement !== runtimeParent) {
    if (connecting) runtimeParent.append($("runtimeCard"));
    else runtimeParent.prepend($("runtimeCard"));
  }
  if (connecting) {
    if ($("publicConnectivityCard").parentElement !== $("connectionPublicHelp")) {
      $("connectionPublicHelp").append($("publicConnectivityCard"));
    }
  } else if ($("publicConnectivityCard").parentElement !== $("technicalDetails").parentElement) {
    $("technicalDetails").before($("publicConnectivityCard"));
  }
}

function renderProduct() {
  const configured = Boolean(productSession && productSession.configured);
  const available = Boolean(latestStatus && latestStatus.product_available);
  const liveRow = configured
    ? productLedgers.find((row) => row.ledger_id === productSession.ledger_id)
    : null;
  const membershipLost = configured && productLedgers.length > 0 && !liveRow;
  const pending = productSession && productSession.pairing_recovery === "original_code_required";
  const showManage = configured && !membershipLost && !pending;
  const productReadFailed = productSessionReadFailed || (showManage && productLedgersReadFailed);
  renderProductLayout(Boolean(productSession) && !showManage && !productReadFailed);
  applyDesktopPairingAvailability();
  $("productFirstUseHelp").hidden = showManage || productReadFailed;
  $("productState").hidden = !showManage && !productReadFailed && available && !pending && !membershipLost;
  if (productReadFailed) {
    $("productTitle").textContent = "桌面账本";
    $("productHomeLink").hidden = true;
    $("productPairGroup").hidden = true;
    $("productManageGroup").hidden = true;
    $("importExportAction").disabled = true;
    $("pairAction").disabled = true;
    $("pairingCodeInput").disabled = true;
    $("switchAction").disabled = true;
    $("unpairAction").disabled = true;
    $("ledgerSelect").disabled = true;
    $("productState").textContent = "账本状态暂不可验证，请稍后重试。";
    return;
  }
  $("productTitle").textContent = showManage ? productSession.ledger_name : "填写连接信息";
  $("productHomeLink").hidden = !(showManage && available);
  $("productPairGroup").hidden = showManage;
  $("productManageGroup").hidden = !showManage;
  // The import/export entry opens the bound ledger's product page; without a
  // live binding it stays disabled so the card never offers a dead click.
  $("importExportAction").disabled = productBusy || !available || !showManage;
  if (!showManage) {
    $("productState").textContent = pending
      ? "上次绑定结果尚未确认，请输入原绑定码继续。若原码已丢失，请等待几分钟，状态更新后再获取新码。"
      : membershipLost ? "原绑定已失效，请使用新的绑定码重新连接。"
        : available ? "获取自己的设备绑定码，连接这台电脑上的桌面账本。"
          : "服务正常后可以把这台电脑连接到账本。";
    $("pairAction").disabled = productBusy || !available;
    $("pairingCodeInput").disabled = productBusy || !available;
    return;
  }
  const roleLabels = {owner: "拥有者", member: "成员", viewer: "只读"};
  // The displayed role follows the live membership row (30s cadence), not
  // the role persisted in WinCred at pair/switch time.
  const role = liveRow ? liveRow.role : productSession.role;
  $("productState").textContent =
    `${roleLabels[role] || role} · ${productSession.account_name}`;
  const select = $("ledgerSelect");
  if (select.options.length === 0) {
    const option = document.createElement("option");
    option.value = productSession.ledger_id;
    option.textContent = productSession.ledger_name;
    select.append(option);
  }
  // A user-chosen, not-yet-switched selection survives the 2.5s refresh
  // ticks; only snap back to the session ledger when nothing is in flight.
  if (!ledgerSelectionDirty) select.value = productSession.ledger_id;
  $("switchAction").disabled = productBusy || !available || select.value === productSession.ledger_id;
  $("unpairAction").disabled = productBusy || !available;
  select.disabled = productBusy || !available;
}

async function loadProductSession(options = {}) {
  try {
    const payload = await productFetch("/api/product/session", options);
    if (!isProductSessionPayload(payload)) throw new Error("product");
    productSession = payload;
    productSessionReadFailed = false;
    if (!productSession || !productSession.configured) {
      productLedgers = [];
      productLedgersReadFailed = false;
      ledgerSelectionDirty = false;
      $("ledgerSelect").replaceChildren();
    }
  } catch (_error) {
    productSession = null;
    productLedgers = [];
    productSessionReadFailed = true;
    productLedgersReadFailed = false;
    ledgerSelectionDirty = false;
    $("ledgerSelect").replaceChildren();
  }
  renderProduct();
}

async function loadProductLedgers(options = {}) {
  if (!productSession || !productSession.configured) {
    productLedgersReadFailed = false;
    return;
  }
  try {
    const payload = await productFetch("/api/product/ledgers", options);
    if (!isProductLedgersPayload(payload)) throw new Error("product");
    productLedgers = payload.ledgers || [];
    productLedgersReadFailed = false;
    const select = $("ledgerSelect");
    // Rebuilding options resets select.value to the first row — carry a
    // dirty user selection across the rebuild (or drop it if the ledger
    // itself vanished from the membership list).
    const inFlight = ledgerSelectionDirty ? select.value : null;
    select.replaceChildren(...productLedgers.map((row) => {
      const option = document.createElement("option");
      option.value = row.ledger_id;
      option.textContent = row.is_current ? `${row.name}（当前）` : row.name;
      return option;
    }));
    if (inFlight && [...select.options].some((option) => option.value === inFlight)) {
      select.value = inFlight;
    } else if (inFlight) {
      ledgerSelectionDirty = false;
    }
    if (!ledgerSelectionDirty) select.value = productSession.ledger_id;
  } catch (_error) {
    productLedgers = [];
    productLedgersReadFailed = true;
    ledgerSelectionDirty = false;
    $("ledgerSelect").replaceChildren();
  }
  renderProduct();
}

async function productAction(work) {
  if (productBusy) return;
  productBusy = true;
  renderProduct();
  try {
    await work();
    setMessage("productError", "");
    ledgerSelectionDirty = false;
    await loadProductSession();
    await loadProductLedgers();
  } catch (error) {
    setMessage("productError", (error && error.message && error.message !== "product")
      ? error.message
      : "未能完成桌面账本操作，请稍后重试。");
  } finally {
    productBusy = false;
    renderProduct();
  }
}

async function pairProduct() {
  const code = $("pairingCodeInput").value.trim();
  if (!/^\d{8}$/.test(code)) {
    setMessage("productError", "请输入 8 位设备绑定码。");
    return;
  }
  await productAction(async () => {
    try {
      await productFetch("/api/product/pair", {method: "POST", body: JSON.stringify({pairing_code: code})});
    } catch (error) {
      // The Controller owns whether an unknown result can start a new attempt.
      await loadProductSession();
      throw error;
    }
    $("pairingCodeInput").value = "";
  });
}

async function unpairProduct() {
  await productAction(async () => {
    await productFetch("/api/product/unpair", {method: "POST", body: ""});
    productLedgers = [];
    $("ledgerSelect").replaceChildren();
  });
}

async function switchProductLedger() {
  const ledgerId = $("ledgerSelect").value;
  if (!ledgerId || (productSession && ledgerId === productSession.ledger_id)) return;
  await productAction(async () => {
    await productFetch("/api/product/ledger/switch", {method: "POST", body: JSON.stringify({ledger_id: ledgerId})});
  });
}

document.addEventListener("change", (event) => {
  if (event.target !== $("ledgerSelect")) return;
  ledgerSelectionDirty = Boolean(
    productSession && $("ledgerSelect").value !== productSession.ledger_id
  );
  renderProduct();
});

async function refresh(refreshDeadlineMs = STATUS_REFRESH_DEADLINE_MS) {
  if (refreshInFlight) return;
  refreshInFlight = true;
  const controller = new AbortController();
  let timeoutId;
  const deadline = new Promise((_resolve, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error("status_timeout"));
      controller.abort();
    }, refreshDeadlineMs);
  });
  try {
    const response = await Promise.race([
      fetch("/api/status", {
        headers: {"X-Control-Token": window.CONTROL_TOKEN},
        signal: controller.signal
      }),
      deadline
    ]);
    if (!response.ok) throw new Error("status");
    render(await Promise.race([response.json(), deadline]));
    const requestOptions = {signal: controller.signal};
    await Promise.race([loadProductSession(requestOptions), deadline]);
    if (productSession && productSession.configured) {
      productLedgerRefreshTick += 1;
      if (productLedgers.length === 0 || productLedgerRefreshTick >= PRODUCT_LEDGER_REFRESH_TICKS) {
        productLedgerRefreshTick = 0;
        await Promise.race([loadProductLedgers(requestOptions), deadline]);
      }
    } else {
      productLedgerRefreshTick = 0;
    }
  } catch (_error) {
    latestStatus = null;
    setOverall("error", "管理器离线");
    setMessage("controlError", "管理器状态暂不可用，请稍后重试。");
    renderPublicConnectivity(null);
    applyActionAvailability(null);
  } finally {
    clearTimeout(timeoutId);
    refreshInFlight = false;
  }
}

async function act(action, button) {
  if (actionInFlight) return;
  const original = button ? button.innerHTML : "";
  const originalAriaLabel = button ? button.getAttribute("aria-label") : null;
  let actionRendered = false;
  actionInFlight = true;
  applyActionAvailability(latestStatus);
  if (button) {
    if (button.classList.contains("button-icon")) {
      button.innerHTML = '<svg class="icon spinner" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#manager-icon-loader-circle"></use></svg>';
      button.setAttribute("aria-label", "处理中");
    } else {
      button.innerHTML = '<svg class="icon spinner" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#manager-icon-loader-circle"></use></svg><span>处理中</span>';
    }
  }
  try {
    const response = await fetch(`/api/${action}`, {
      method: "POST",
      headers: {"X-Control-Token": window.CONTROL_TOKEN}
    });
    if (response.status === 409) throw new Error("busy");
    if (!response.ok) throw new Error("action");
    render(await response.json());
    actionRendered = true;
  } catch (error) {
    setMessage(
      "controlError",
      error.message === "busy" ? "另一项操作正在进行，请等待完成。" : "管理器未能完成操作，请稍后重试。"
    );
  } finally {
    if (button && (!actionRendered || button.id !== "primaryAction")) {
      button.innerHTML = original;
      if (originalAriaLabel === null) button.removeAttribute("aria-label");
      else button.setAttribute("aria-label", originalAriaLabel);
    }
    actionInFlight = false;
    applyActionAvailability(latestStatus);
    await refresh();
  }
}

function openImportExport() {
  if ($("importExportAction").disabled) return;
  window.location.assign("/web/import");
}
