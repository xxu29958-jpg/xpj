/* Native repayment form: retain one bound submission; only the server accepts it. */
(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-repayment-scope]");
  if (!form) return;
  const names = ["debt_public_id", "ledger_id", "origin_binding", "home_currency_code",
    "expected_row_version", "amount_major", "paid_at", "paid_at_timezone"];
  const axes = ["datasetId", "clientGeneration", "accountId", "ledgerId", "deviceId"];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const panel = document.querySelector("[data-repayment-panel]");
  const shelf = document.querySelector("[data-repayment-shelf]");
  const status = form.querySelector("[data-repayment-status]");
  const submit = form.querySelector("[data-repayment-submit]");
  const replace = form.querySelector("[data-repayment-replace]");
  const controls = names.map(name => form.elements.namedItem(name));
  const refInput = form.elements.namedItem("idempotency_key");
  const nativeRef = refInput.value, target = form.dataset.repaymentTarget;
  const nativeValues = values(), canCreate = form.dataset.repaymentCanCreate === "true";
  const canRecover = form.dataset.repaymentCanRecover === "true";
  let nativeResult = form.dataset.repaymentResult;
  let scope, drafts, leaseKey, replacement, acknowledged = "";
  let currentRef = "", phase = "blocked", held = false, retained = false, posting = false;
  let release = null, epoch = 0, leaseFinished = Promise.resolve(), ready = Promise.resolve(), pageActive = true;

  function values() {
    return Object.fromEntries(controls.map(control => [control.name, control.value]));
  }
  function sameValues(left, right) {
    return names.every(name => typeof left[name] === "string" && left[name] === right[name]);
  }
  function bound(saved) {
    return saved.debt_public_id === target && saved.ledger_id === scope.ledgerId &&
      drafts.matches(JSON.parse(saved.origin_binding), scope);
  }
  function notice(message, state) {
    status.hidden = false;
    status.textContent = message;
    form.dataset.repaymentState = state;
  }
  function lockInputs(locked) {
    controls.forEach(control => { control.readOnly = locked; });
  }
  function showValues(saved) {
    controls.forEach(control => { control.value = saved[control.name]; });
    const label = form.querySelector('label[for="debt-repay-amount"]');
    if (label) label.textContent = "本次还款（" + (saved.home_currency_code || "原币种") + "）";
  }
  function blocked(message, state = "blocked") {
    phase = "blocked";
    lockInputs(true);
    submit.disabled = true;
    if (replace) replace.hidden = true;
    notice(message, state);
  }
  function showPhase() {
    panel.hidden = false;
    lockInputs(phase !== "editing");
    const canReplace = replacement && phase === "blocked" && currentRef === nativeRef;
    submit.disabled = phase === "editing" ? !canCreate : !canRecover || !!canReplace;
    submit.textContent = phase !== "editing" ? "继续核实这笔还款" : "记一笔还款";
    notice(phase === "submitted" ? "结果尚未确认。继续核实会发送原来的金额、日期和提交编号。" :
      phase === "blocked" ? "原提交已保留，请先核对欠款和当前身份。" : "输入会保留在此浏览器，尚未提交。", phase);
    if (replace) replace.hidden = !canReplace;
  }
  function records() {
    return drafts.list(scope).filter(record => record.values.debt_public_id === target);
  }
  function renderShelf() {
    const items = records(), list = shelf.querySelector("[data-repayment-list]");
    list.replaceChildren();
    items.forEach(record => {
      const item = document.createElement("li"), link = document.createElement("a");
      link.href = window.location.pathname + window.location.search + "#repayment-" + record.clientRef;
      link.textContent = [record.values.home_currency_code, record.values.amount_major || "未填金额",
        record.values.paid_at, !drafts.matches(record.scope, scope) ? "旧身份，待核对" :
          record.phase === "submitted" ? "结果待确认" : record.phase === "blocked" ? "待核对" : "未提交"].join(" · ");
      item.append(link);
      list.appendChild(item);
    });
    shelf.hidden = items.length === 0;
    return items;
  }
  function fragmentRef() {
    const ref = window.location.hash.replace(/^#repayment-/, "");
    return window.location.hash.startsWith("#repayment-") && uuid.test(ref) ? ref : "";
  }
  function pointTo(ref) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search +
      (ref ? "#repayment-" + ref : ""));
  }
  function persist(nextPhase) {
    const original = drafts.read(currentRef);
    if (retained && !original) throw Error("original_removed");
    const creating = !original || original.phase === "editing";
    if (!bound(values()) || (creating && records().some(record => record.clientRef !== currentRef))) {
      throw Error("another_original_submission");
    }
    drafts.save(scope, currentRef, nextPhase, values());
    retained = true;
    pointTo(currentRef);
  }

  function selectSubmission(items) {
    let requested = fragmentRef();
    if (requested === acknowledged) requested = "";
    const nativePending = nativeResult && nativeRef !== acknowledged;
    if (nativePending) return {ref:nativeRef, requested, nativePending};
    if (requested) return {ref:requested, requested};
    const preferred = items.find(record => record.phase !== "editing") || items[0];
    const freshRef = canCreate && nativeRef !== acknowledged ? nativeRef : "";
    return {ref:preferred ? preferred.clientRef : freshRef, requested:""};
  }
  function admitSubmission(record, selection, count) {
    if (count > 1 && (record ? record.phase === "editing" : !selection.nativePending)) {
      blocked("此欠款还有原提交待核对。请从下方打开原提交继续核实，当前不会发送新的还款。");
      return false;
    }
    if (record) {
      if (drafts.matches(record.scope, scope) && bound(record.values)) return true;
      if (drafts.matches(record.scope, scope, false) && record.values.debt_public_id === target) showValues(record.values);
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
    if (record && !sameValues(record.values, nativeValues)) {
      blocked("返回结果与保留的原提交不一致，请先核对，原输入未被改写。");
      return;
    }
    const rejected = nativeResult === "rejected";
    phase = rejected ? "editing" : nativeResult;
    showValues(nativeValues);
    drafts.save(scope, currentRef, phase, nativeValues, rejected ? "rejected" : "");
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

  async function acknowledge() {
    const marker = document.querySelector("[data-repayment-ack]");
    if (!marker) return;
    const ackStatus = document.querySelector("[data-repayment-ack-status]");
    try {
      const ack = JSON.parse(marker.getAttribute("data-repayment-ack"));
      if (!uuid.test(ack.clientRef) || !uuid.test(ack.repaymentPublicId) ||
          !drafts.matches(ack.scope, scope) || !bound(ack.values)) throw Error("ack_mismatch");
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

  form.addEventListener("input", function () {
    if (!held || phase !== "editing") return;
    try { persist("editing"); notice("输入已保留，尚未提交。", "editing"); }
    catch (_) { notice("最新输入未能保留。请勿关闭本页，恢复存储后再提交。", "storage-error"); }
  });
  form.addEventListener("submit", function (event) {
    if (!held || submit.disabled || posting) { event.preventDefault(); return; }
    try {
      if (phase !== "editing") {
        const record = drafts.read(currentRef);
        if (!record || record.phase === "editing" || !drafts.matches(record.scope, scope)) throw Error("original_missing");
        showValues(record.values);
      }
      persist("submitted");
      phase = "submitted"; posting = true; lockInputs(true); submit.disabled = true;
      notice("正在提交原来的这笔还款…", "submitting");
    } catch (_) {
      event.preventDefault();
      notice("原提交未能安全保留，这次没有发送。请保留本页并检查浏览器存储。", "storage-error");
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
    if (!uuid.test(next.clientRef) || next.clientRef === currentRef || !bound(next.values) ||
        !sameValues({...next.values, expected_row_version:previous.values.expected_row_version}, previous.values)) {
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
    drafts = window.TicketboxDraftStore.createStore({prefix:"ticketbox:repayment-draft:v1:", fields:names, validRef:uuid});
    leaseKey = "ticketbox:repayment-lease:v1:" + JSON.stringify([...axes.map(axis => scope[axis]), target]);
    replacement = form.dataset.repaymentReplacement ? JSON.parse(form.dataset.repaymentReplacement) : null;
    ready = acknowledge();
    resume();
  } catch (_) { blocked("当前无法安全保留还款原提交。请保留输入，检查身份和浏览器存储后再试。"); }
})(window, document);
