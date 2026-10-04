/* Native repayment form: retain one bound submission; only the server accepts it. */
(function (window, document) {
  "use strict";
  const repaymentNames = ["debt_public_id", "ledger_id", "origin_binding", "home_currency_code",
    "expected_row_version", "amount_major", "paid_at", "paid_at_timezone"];
  const voidNames = ["debt_public_id", "ledger_id", "origin_binding", "expected_row_version", "reason", "repayment_public_id"];
  const kindNames = ["debt_public_id", "ledger_id", "origin_binding", "expected_row_version", "debt_kind"];
  const fieldNames = {repayment:repaymentNames, "debt-void":voidNames, "repayment-void":voidNames,
    "repayment-review":["draft_public_id", "ledger_id", "origin_binding", "review_action", "target_with_expected_row_version", "original_currency", "original_amount"],
    "debt-kind":kindNames, "split-change":["debt_public_id", "ledger_id", "origin_binding", "home_currency_code", "command",
      "proposal_public_id", "expected_row_version", "expected_return_row_version", "new_share_amount_major",
      "settlement_net_amount_major", "reason", "supersedes_proposal_public_id"]};
  const voidLabels = ["确认作废", "继续核实原作废"];
  const submitLabels = {repayment:["记一笔还款", "继续核实这笔还款"],
    "debt-void":voidLabels, "repayment-void":voidLabels,
    "debt-kind":["保存偿还方式", "继续核实原更正"], "repayment-review":["确认处理", "核实原处理"]};
  function bindBalancePreview(form) {
    const panel = form.querySelector("[data-debt-balance-preview]");
    if (!panel) return null;
    const input = form.elements.namedItem("amount_major");
    const output = panel.querySelector("[data-balance-after]");
    const digits = Number(panel.dataset.balanceDigits);
    const before = BigInt(panel.dataset.balanceMinor);
    const scale = 10n ** BigInt(digits);
    function update() {
      panel.hidden = true;
      const currency = form.elements.namedItem("home_currency_code");
      const version = form.elements.namedItem("expected_row_version");
      if (input.readOnly || currency && currency.value !== panel.dataset.balanceCurrency ||
          version && version.value !== panel.dataset.balanceVersion) return;
      // This estimates only exact positive input. It never normalizes a command,
      // clamps an overpayment, or represents an unknown submission as accepted.
      const match = /^(0|[1-9][0-9]*)(?:\.([0-9]+))?$/.exec(input.value.trim());
      if (!match) return;
      const fraction = match[2] || "";
      if (/[^0]/.test(fraction.slice(digits))) return;
      const minor = BigInt(match[1]) * scale + BigInt(fraction.slice(0, digits).padEnd(digits, "0") || "0");
      if (minor <= 0n || minor > before) return;
      const after = before - minor;
      const whole = (after / scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      output.textContent = panel.dataset.balanceSymbol + whole +
        (digits ? "." + (after % scale).toString().padStart(digits, "0") : "");
      panel.hidden = false;
    }
    form.addEventListener("input", update);
    update();
    return update;
  }
  function initialize(form, settlementField) {
  const surface = form.closest("[data-repayment-container]");
  if (!surface) return;
  const voidCommand = ["debt-void", "repayment-void"].includes(form.dataset.repaymentKind);
  const splitChange = form.dataset.repaymentKind === "split-change";
  const kindCorrection = form.dataset.repaymentKind === "debt-kind";
  const captureReview = form.dataset.repaymentKind === "repayment-review";
  const targetField = captureReview ? "draft_public_id" : "debt_public_id";
  const typedCorrection = voidCommand || kindCorrection || captureReview;
  const namespace = Object.hasOwn(fieldNames, form.dataset.repaymentKind) ? form.dataset.repaymentKind : "repayment";
  const names = fieldNames[namespace];
  const kindLabels = {one_off:"一次结清", revolving:"循环往来", installment:"分期偿还", unspecified:"暂不指定"};
  const commandLabels = {create:"发送新约定", accept:"接受这份约定", reject:"拒绝这份约定", withdraw:"撤回我的约定"};
  const axes = ["datasetId", "clientGeneration", "accountId", "ledgerId", "deviceId"];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const panel = surface.querySelector("[data-repayment-panel]");
  const shelf = surface.querySelector("[data-repayment-shelf]");
  const status = form.querySelector("[data-repayment-status]");
  const submit = form.querySelector("[data-repayment-submit]");
  const replace = form.querySelector("[data-repayment-replace]");
  const preview = form.querySelector("[data-repayment-preview]");
  const updateBalancePreview = bindBalancePreview(form);
  const settlementExplicit = form.elements.namedItem("settlement_explicit");
  const optionalNames = splitChange ? ["settlement_explicit", "settlement_suggestion"] : [];
  const hints = optionalNames.map(name => form.elements.namedItem(name)).filter(Boolean);
  const finishReview = form.querySelector("[data-void-finish-review]");
  const finishRejected = form.querySelector("[data-void-finish-rejected]");
  const rejectionReview = form.querySelector("[data-void-rejection-review]");
  const nativeRejected = form.dataset.voidRejected === "true";
  let knownRejected = false;
  const controls = names.map(name => form.elements.namedItem(name));
  const refInput = form.elements.namedItem("idempotency_key");
  const nativeRef = refInput.value, target = form.dataset.repaymentTarget;
  const selectOriginals = new Map(controls.filter(control => control.tagName === "SELECT").map(control => {
    const original = document.createElement("input");
    original.type = "hidden"; original.name = control.name; original.disabled = true;
    form.appendChild(original);
    return [control, original];
  }));
  const nativeValues = values(), canCreate = form.dataset.repaymentCanCreate === "true";
  const canRecover = form.dataset.repaymentCanRecover === "true";
  let allowedCommand = canCreate ? nativeValues : null;
  let nativeResult = form.dataset.repaymentResult;
  let scope, drafts, leaseKey, replacement, acknowledged = "";
  let currentRef = "", phase = "blocked", held = false, retained = false, posting = false;
  let release = null, epoch = 0, leaseFinished = Promise.resolve(), ready = Promise.resolve(), pageActive = true;

  function values() {
    const result = Object.fromEntries(controls.map(control => [control.name, control.value]));
    hints.forEach(control => { if (control.value !== "") result[control.name] = control.value; });
    return result;
  }
  function sameValues(left, right) {
    return names.every(name => typeof left[name] === "string" && left[name] === right[name]);
  }
  function bound(saved) {
    return saved[targetField] === target && saved.ledger_id === scope.ledgerId &&
      drafts.matches(JSON.parse(saved.origin_binding), scope);
  }
  function notice(message, state) {
    status.hidden = false;
    status.textContent = captureReview ? message.replaceAll("还款", "采集处理").replaceAll("欠款", "原采集") : kindCorrection ? message.replaceAll("还款", "偿还方式更正").replaceAll("金额、日期", "选择、版本") : voidCommand ? message.replaceAll("还款", "作废提交").replaceAll("金额、日期", "对象、原因") : splitChange ? message.replaceAll("还款", "约定操作") : message;
    form.dataset.repaymentState = state;
    updateBalancePreview?.();
  }
  function lockInputs(locked) {
    controls.forEach(control => {
      control.readOnly = locked;
      const original = selectOriginals.get(control);
      if (original) {
        control.disabled = locked;
        original.value = control.value;
        original.disabled = !locked;
      }
    });
    settlementField?.sync();
    updateBalancePreview?.();
  }
  function showValues(saved) {
    controls.forEach(control => {
      const value = saved[control.name];
      if (control.tagName === "SELECT" && control.options && !Array.from(control.options).some(option => option.value === value)) {
        const option = document.createElement("option");
        option.value = value; option.textContent = "原选择（需核对）";
        control.appendChild(option);
      }
      control.value = value;
    });
    hints.forEach(control => { control.value = saved[control.name] ?? ""; });
    settlementField?.sync();
    if (splitChange) {
      if (!commandLabels[saved.command]) throw Error("invalid_original_command");
      const base = "/web/debts/" + encodeURIComponent(saved.debt_public_id) + "/split-changes";
      form.action = saved.command === "create" ? base :
        base + "/" + encodeURIComponent(saved.proposal_public_id) + "/" + saved.command;
      const heading = document.querySelector("[data-split-command-title]");
      const originalCommand = form.querySelector("[data-split-original-command]");
      if (heading) heading.textContent = commandLabels[saved.command];
      if (originalCommand) originalCommand.hidden = saved.command === "create";
      if (preview) preview.hidden = saved.command !== "create";
    }
    const label = form.querySelector('label[for="debt-repay-amount"]');
    if (label) label.textContent = "本次还款（" + (saved.home_currency_code || "原币种") + "）";
    updateBalancePreview?.();
  }
  function blocked(message, state = "blocked") {
    phase = "blocked";
    lockInputs(true);
    submit.disabled = true;
    if (replace) replace.hidden = true;
    notice(message, state);
    panel.open = true;
  }
  function commandControls(editing) {
    if (!splitChange) {
      lockInputs(!editing || captureReview && !canCreate);
      submit.textContent = submitLabels[namespace][editing ? 0 : 1];
      return canCreate;
    }
    const command = values().command, writable = command === "create";
    lockInputs(!editing || !writable);
    if (preview) preview.disabled = !editing || !writable;
    submit.textContent = editing ? commandLabels[command] : "核实原约定操作";
    return allowedCommand && ["command", "proposal_public_id", "supersedes_proposal_public_id"]
      .every(name => values()[name] === allowedCommand[name]);
  }
  function showPhase() {
    panel.hidden = false;
    if (retained) panel.open = true;
    const canEdit = commandControls(phase === "editing");
    const canReplace = replacement && phase === "blocked" && currentRef === nativeRef;
    submit.disabled = phase === "editing" ? !canEdit : !canRecover || !!canReplace || !!finishReview || knownRejected;
    if (finishRejected) finishRejected.hidden = !knownRejected;
    if (rejectionReview) rejectionReview.hidden = !knownRejected;
    notice(phase === "submitted" ? "结果尚未确认。继续核实会沿用原提交内容和编号。" :
      phase === "blocked" ? "原提交已保留，请先核对欠款和当前身份。" : "输入会保留在此浏览器，尚未提交。", phase);
    if (replace) replace.hidden = !canReplace;
  }
  function records() {
    return drafts.list(scope).filter(record => record.values[targetField] === target &&
      (!voidCommand || namespace !== "repayment-void" || !nativeValues.repayment_public_id ||
        record.values.repayment_public_id === nativeValues.repayment_public_id));
  }
  function renderShelf() {
    const items = records(), list = shelf.querySelector("[data-repayment-list]");
    list.replaceChildren();
    items.forEach(record => {
      const item = document.createElement("li"), link = document.createElement("a");
      link.href = window.location.pathname + window.location.search + "#" + namespace + "-" + record.clientRef;
      const stateLabel = !drafts.matches(record.scope, scope) ? "旧身份，待核对" :
        record.phase === "submitted" ? "结果待确认" : record.phase === "blocked" ? "待核对" : "未提交";
      link.textContent = [...describeOriginal(record.values), stateLabel].join(" · ");
      item.append(link);
      list.appendChild(item);
    });
    shelf.hidden = items.length === 0;
    return items;
  }
  function describeOriginal(saved) {
    if (captureReview) return [saved.review_action === "dismiss" ? "忽略通知" : "记为还款", saved.original_currency, saved.original_amount || "未填金额"];
    if (kindCorrection) return [kindLabels[saved.debt_kind] || saved.debt_kind];
    if (voidCommand) return [saved.home_currency_code, saved.reason || "未填原因", saved.repayment_public_id || saved.debt_public_id];
    if (splitChange) return [saved.home_currency_code, commandLabels[saved.command], saved.new_share_amount_major];
    return [saved.home_currency_code, saved.amount_major || "未填金额", saved.paid_at];
  }
  function fragmentRef() {
    const prefix = "#" + namespace + "-", ref = window.location.hash.slice(prefix.length);
    return window.location.hash.startsWith(prefix) && uuid.test(ref) ? ref : "";
  }
  function pointTo(ref) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search +
      (ref ? "#" + namespace + "-" + ref : ""));
  }
  function persist(nextPhase) {
    const original = drafts.read(currentRef);
    if (retained && !original) throw Error("original_removed");
    const creating = !original || original.phase === "editing";
    if (!splitChange && creating && anotherDebtSubmission()) throw Error("another_original_submission");
    if (!bound(values()) || (creating && records().some(record => record.clientRef !== currentRef &&
        (!splitChange || record.phase !== "editing")))) {
      throw Error("another_original_submission");
    }
    drafts.save(scope, currentRef, nextPhase, values());
    retained = true;
    pointTo(currentRef);
  }
  function anotherDebtSubmission() {
    function parent(saved, kind) {
      return kind === "repayment-review" ? (saved.review_action === "confirm" ? saved.target_with_expected_row_version.split(":")[0] : "") : saved.debt_public_id;
    }
    const debt = parent(values(), namespace);
    if (!debt) return false;
    return ["repayment", "debt-void", "repayment-void", "debt-kind", "repayment-review"].some(kind => {
      const store = window.TicketboxDraftStore.createStore({prefix:"ticketbox:" + kind + "-draft:v1:",
        fields:fieldNames[kind], validRef:uuid});
      return store.list(scope).some(record => parent(record.values, kind) === debt &&
        (kind !== namespace || record.clientRef !== currentRef) && record.phase !== "editing");
    });
  }

  function selectSubmission(items) {
    let requested = fragmentRef();
    if (requested === acknowledged) requested = "";
    const nativePending = nativeResult && nativeRef !== acknowledged;
    if (nativePending) return {ref:nativeRef, requested, nativePending};
    if (requested) return {ref:requested, requested};
    const preferred = items.find(record => record.phase !== "editing") || (splitChange ?
      items.find(record => record.values.command === nativeValues.command &&
        record.values.proposal_public_id === nativeValues.proposal_public_id &&
        record.values.supersedes_proposal_public_id === nativeValues.supersedes_proposal_public_id) : items[0]);
    const freshRef = canCreate && nativeRef !== acknowledged ? nativeRef : "";
    return {ref:preferred ? preferred.clientRef : freshRef, requested:""};
  }
  function admitSubmission(record, selection, count) {
    if (!splitChange && count > 1 && (record ? record.phase === "editing" : !selection.nativePending)) {
      blocked("此欠款还有原提交待核对。请从下方打开原提交继续核实，当前不会发送新的还款。");
      return false;
    }
    if (record) {
      if (drafts.matches(record.scope, scope) && bound(record.values)) return true;
      if (drafts.matches(record.scope, scope, false) && record.values[targetField] === target) showValues(record.values);
      blocked("这是原身份的还款，仅供核对，不会转移到当前身份重新提交。");
      return false;
    }
    if (selection.requested) {
      blocked("这份原提交已收起或移除。请先核对还款事实，不会重新创建它。");
      return false;
    }
    if (bound(nativeValues)) return true;
    blocked("原提交的身份或欠款不匹配，输入仍保留，当前不会发送。");
    return false;
  }
  function applyNativeResult(record) {
    const previewResult = splitChange && nativeResult === "preview";
    if (previewResult && record && record.phase !== "editing") {
      blocked("原提交结果尚未核实，不能用预览改写。请从保留任务继续核实。");
      return;
    }
    if (!previewResult && record && !sameValues(record.values, nativeValues)) {
      knownRejected = record.serverResult === "rejected";
      blocked("返回结果与保留的原提交不一致，请先核对，原输入未被改写。");
      return;
    }
    const rejected = nativeResult === "rejected";
    phase = rejected || previewResult ? "editing" : nativeResult === "accepted-review" ? "blocked" : nativeResult;
    showValues(nativeValues);
    drafts.save(scope, currentRef, phase, nativeValues, rejected || knownRejected ? "rejected" : "");
    retained = true;
    pointTo(currentRef);
    showPhase();
  }
  function openSubmission() {
    const items = renderShelf(), selection = selectSubmission(items);
    if (!selection.ref) { panel.hidden = true; return false; }
    if (!uuid.test(selection.ref)) {
      blocked("原提交编号无法读取，内容未被覆盖。请保留本页核对。");
      return false;
    }
    const record = drafts.read(selection.ref);
    currentRef = selection.ref; refInput.value = currentRef; retained = !!record;
    held = true; panel.hidden = false;
    if (admitSubmission(record, selection, items.length)) {
      phase = record ? record.phase : "editing";
      knownRejected = typedCorrection && (!!record && record.serverResult === "rejected" ||
        selection.nativePending && nativeRejected);
      if (record) { showValues(record.values); pointTo(currentRef); }
      if (selection.nativePending) applyNativeResult(record);
      else showPhase();
    }
    nativeResult = "";
    return true;
  }
  function activate() {
    const turn = ++epoch;
    const previousLease = leaseFinished;
    if (release) release();
    held = false; release = null; posting = false;
    lockInputs(true); submit.disabled = true;
    leaseFinished = previousLease.then(function () {
      if (turn !== epoch) return;
      if (voidCommand) {
        const selection = selectSubmission(records());
        if (!selection.ref) { panel.hidden = true; return; }
        const record = drafts.read(selection.ref);
        const repaymentTarget = (record ? record.values : nativeValues).repayment_public_id;
        leaseKey = "ticketbox:" + namespace + "-lease:v1:" + JSON.stringify([...axes.map(axis => scope[axis]), target, repaymentTarget]);
      }
      return window.navigator.locks.request(leaseKey, {ifAvailable:true}, function (lock) {
        if (turn !== epoch) return;
        if (!lock) {
          blocked("这笔欠款正在另一个标签页核对。请回到那个页面，或关闭后刷新本页。", "locked");
          return;
        }
        if (!openSubmission()) return;
        return new Promise(resolve => { release = resolve; });
      });
    }).catch(function () {
      if (turn !== epoch) return;
      held = false;
      blocked("原输入暂时无法读取或保留。请勿关闭本页，检查浏览器存储后再试。", "storage-error");
    });
  }

  function acknowledgesCommand(ack) {
    if (typedCorrection && ack.resultPublicId !== target) return false;
    if (captureReview) return ack.status === {confirm:"confirmed", dismiss:"dismissed"}[ack.values.review_action] &&
      (ack.status !== "confirmed" || uuid.test(ack.repaymentPublicId));
    if (kindCorrection) return ack.debtKind === ack.values.debt_kind;
    return true;
  }
  async function acknowledge() {
    const marker = surface.querySelector("[data-repayment-ack]");
    if (!marker) return;
    const ackStatus = surface.querySelector("[data-repayment-ack-status]");
    try {
      const ack = JSON.parse(marker.getAttribute("data-repayment-ack"));
      if (!uuid.test(ack.clientRef) || !uuid.test(splitChange || typedCorrection ? ack.resultPublicId : ack.repaymentPublicId) ||
          !acknowledgesCommand(ack) ||
          !drafts.matches(ack.scope, scope) || !bound(ack.values)) throw Error("ack_mismatch");
      if (voidCommand) leaseKey = "ticketbox:" + namespace + "-lease:v1:" +
        JSON.stringify([...axes.map(axis => scope[axis]), target, ack.values.repayment_public_id]);
      await window.navigator.locks.request(leaseKey, {ifAvailable:true}, function (lock) {
        if (!lock) throw Error("ack_lease_unavailable");
        const record = drafts.read(ack.clientRef);
        if (record && (!drafts.matches(record.scope, scope) || !sameValues(record.values, ack.values))) {
          throw Error("ack_original_mismatch");
        }
        if (record && !drafts.acknowledge(ack)) throw Error("ack_not_applied");
        acknowledged = ack.clientRef;
        if (fragmentRef() === acknowledged) pointTo("");
      });
    } catch (_) {
      if (ackStatus) ackStatus.textContent = " 浏览器原提交尚未收起，请保留并核对后再继续。";
    }
  }

  form.addEventListener("input", function (event) {
    if (!held || phase !== "editing") return;
    const settlementEdited = settlementField?.edit(event.target) || event.target?.name === "settlement_net_amount_major";
    if (settlementExplicit && settlementEdited) settlementExplicit.value = "true";
    try { persist("editing"); notice("输入已保留，尚未提交。", "editing"); }
    catch (_) { notice("最新输入未能保留。请勿关闭本页，恢复存储后再提交。", "storage-error"); }
  });
  function finishOriginal(button, serverResult) {
    if (!button) return;
    button.addEventListener("click", function () {
      if (!held || phase !== "blocked" || (serverResult === "accepted-review" && currentRef !== nativeRef)) return;
      try {
        const discard = serverResult === "rejected" ? drafts.discardRejected : drafts.discardReviewed;
        if (serverResult === "rejected" && (!knownRejected || drafts.read(currentRef)?.serverResult !== "rejected")) return;
        if (!discard({scope, clientRef:currentRef,
            values:serverResult === "rejected" ? values() : nativeValues, serverResult})) throw Error("review_original_mismatch");
        retained = false;
        pointTo("");
        blocked(serverResult === "rejected" ? "已结束这次未接受的本地提交。核对当前记录后可重新填写。" :
          kindCorrection ? "已结束本地恢复。原更正记录仍保留，请在原记录核对。" :
          "已结束本地恢复。原作废事实仍保留，可在原记录与往来历史核对。");
        button.disabled = true;
        renderShelf();
      } catch (_) { blocked("原提交尚未收起，请保留并核对浏览器存储。"); }
    });
  }
  finishOriginal(finishReview, "accepted-review");
  finishOriginal(finishRejected, "rejected");
  form.addEventListener("submit", function (event) {
    const previewing = preview && event.submitter === preview;
    if (!held || posting || (previewing ? preview.disabled : submit.disabled)) { event.preventDefault(); return; }
    try {
      if (previewing) {
        if (phase !== "editing") throw Error("original_is_submitted");
        persist("editing");
        return;
      }
      if (phase !== "editing") {
        const record = drafts.read(currentRef);
        if (!record || record.phase === "editing" || !drafts.matches(record.scope, scope)) throw Error("original_missing");
        showValues(record.values);
      }
      persist("submitted");
      phase = "submitted"; posting = true; lockInputs(true); submit.disabled = true;
      notice("正在提交原来的这笔还款…", "submitting");
    } catch (error) {
      event.preventDefault();
      notice(error.message === "another_original_submission" ?
        "这笔欠款还有原提交待核对。这次没有发送，请先打开原提交继续核实。" :
        "原提交未能安全保留，这次没有发送。请保留本页并检查浏览器存储。", "storage-error");
    }
  });
  function matchingDraft(record, expectedPhase, saved) {
    return record && record.phase === expectedPhase && drafts.matches(record.scope, scope) &&
      sameValues(record.values, saved);
  }
  function replacementDraft(previous) {
    if (!matchingDraft(previous, "blocked", nativeValues)) throw Error("replacement_mismatch");
    const candidate = records().find(record => matchingDraft(record, "editing", replacement.values));
    const next = candidate || replacement;
    const comparison = {...next.values, expected_row_version:previous.values.expected_row_version};
    if (splitChange) ["expected_return_row_version", "command", "proposal_public_id", "supersedes_proposal_public_id"]
      .forEach(name => { comparison[name] = previous.values[name]; });
    if (!uuid.test(next.clientRef) || next.clientRef === currentRef || !bound(next.values) ||
        !sameValues(comparison, previous.values)) {
      throw Error("replacement_mismatch");
    }
    const existing = drafts.read(next.clientRef);
    if (existing && !matchingDraft(existing, "editing", next.values)) throw Error("replacement_already_used");
    return next;
  }
  if (replace) replace.addEventListener("click", function () {
    if (!held || phase !== "blocked" || currentRef !== nativeRef || !replacement) return;
    let verified = false;
    try {
      const previous = drafts.read(currentRef), next = replacementDraft(previous);
      verified = true;
      drafts.save(scope, next.clientRef, "editing", next.values);
      if (!drafts.discardRejected({scope, clientRef:currentRef, values:previous.values,
          serverResult:"rejected"})) throw Error("refusal_not_retired");
      currentRef = next.clientRef; refInput.value = currentRef; phase = "editing";
      // Only the server's explicit rejected-intent correction grants this new
      // command context; general draft permission never does.
      if (splitChange) allowedCommand = next.values;
      retained = true; replacement = null; showValues(next.values); pointTo(currentRef); showPhase(); renderShelf();
    } catch (_) {
      blocked("纠正后的输入尚未完整保留，当前没有发送。请恢复浏览器存储后再点击纠正。", "storage-error");
      if (verified) replace.hidden = false;
    }
  });
  function resume() {
    ready.then(function () { if (pageActive && drafts) activate(); });
  }
  window.addEventListener("pagehide", function () {
    ++epoch; pageActive = false; held = false; lockInputs(true); submit.disabled = true;
    if (release) release();
    release = null;
  });
  window.addEventListener("pageshow", function (event) { pageActive = true; if (event.persisted) resume(); });
  window.addEventListener("hashchange", resume);
  window.addEventListener("storage", function () {
    try {
      renderShelf();
      if (held && retained && !drafts.read(currentRef)) blocked("原提交已在另一页面收起，请先核对事实。");
    } catch (_) { blocked("浏览器原提交暂时无法读取，请保留本页。", "storage-error"); }
  });
  lockInputs(true); submit.disabled = true;
  if (replace) replace.hidden = true;
  try {
    scope = JSON.parse(form.dataset.repaymentScope);
    if (!axes.every(axis => typeof scope[axis] === "string" && scope[axis] && scope[axis].length <= 256) ||
        !window.navigator.locks) throw Error("binding_or_locking_unavailable");
    drafts = window.TicketboxDraftStore.createStore({prefix:"ticketbox:" + namespace + "-draft:v1:", fields:names,
      optionalFields:optionalNames, validRef:uuid});
    leaseKey = "ticketbox:" + namespace + "-lease:v1:" + JSON.stringify([...axes.map(axis => scope[axis]), target]);
    replacement = form.dataset.repaymentReplacement ? JSON.parse(form.dataset.repaymentReplacement) : null;
    ready = acknowledge();
    resume();
  } catch (_) { blocked("当前无法安全保留还款原提交。请保留输入，检查身份和浏览器存储后再试。"); }
  }
  document.querySelectorAll("[data-repayment-scope]").forEach(form => {
    const settlementField = window.TicketboxSplitSettlement ? window.TicketboxSplitSettlement(form) : null;
    initialize(form, settlementField);
  });
  document.querySelectorAll("[data-proposal-balance-preview]").forEach(bindBalancePreview);
})(window, document);
