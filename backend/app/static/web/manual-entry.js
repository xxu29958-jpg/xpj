/* Progressive native-form consumer. The server remains the sole command owner. */
(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-manual-draft-scope]");
  if (!form) return;
  const drafts = window.TicketboxManualDrafts;
  const fields = form.querySelector("[data-manual-edit-fields]");
  const submit = form.querySelector("[data-manual-submit]");
  const status = form.querySelector("[data-manual-draft-status]");
  const options = form.querySelector("[data-manual-options]");
  const actions = document.querySelector("[data-manual-draft-actions]");
  const shelf = document.querySelector("[data-manual-draft-shelf]");
  const controls = drafts.fields.map(name => form.elements.namedItem(name));
  const refInput = form.elements.namedItem("client_ref");
  const nativeRef = refInput.value;
  let nativeResult = form.dataset.manualDraftResult;
  let scope;
  let currentRef = nativeRef;
  let phase = "editing";
  let held = false;
  let release = null;
  let epoch = 0;
  let retained = false;
  let posting = false;

  function notice(message, state) {
    status.textContent = message;
    status.hidden = false;
    form.dataset.manualDraftState = state;
  }

  function values() {
    return Object.fromEntries(controls.map(control => [control.name, control.value]));
  }

  const nativeValues = values();

  function showValues(saved) {
    controls.forEach(control => { control.value = saved[control.name]; });
    if (saved.merchant || saved.note || saved.category !== nativeValues.category ||
        saved.spent_at !== nativeValues.spent_at) options.open = true;
  }

  function readOnly(value) {
    controls.forEach(control => {
      if (control.tagName === "SELECT") control.disabled = value;
      else control.readOnly = value;
    });
  }

  function blocked(message) {
    phase = "blocked";
    fields.disabled = false;
    readOnly(true);
    submit.disabled = true;
    actions.hidden = false;
    notice(message, "blocked");
  }

  function showPhase(restored) {
    fields.disabled = false;
    readOnly(phase !== "editing");
    submit.disabled = phase === "blocked";
    submit.textContent = phase === "submitted" ? "重试这笔支出" : "记下这笔支出";
    actions.hidden = phase === "editing";
    if (phase === "submitted") {
      notice("还未确认保存结果。输入已锁定；重试会提交原来这一笔，也可以先核对流水。", "submitted");
    } else if (phase === "blocked") {
      notice("这份草稿暂不能提交，输入仍在。请先核对流水与当前账号、账本。", "blocked");
    } else {
      notice(restored ? "草稿已恢复，继续这一笔。" : "填写后自动保留在此浏览器。", "editing");
    }
  }

  function renderShelf() {
    const records = drafts.list(scope);
    const list = shelf.querySelector("[data-manual-draft-list]");
    list.replaceChildren();
    records.forEach(record => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = "/web/expenses/new#manual-" + record.clientRef;
      link.textContent = [record.values.currency_code, record.values.amount_major || "未填金额",
        record.values.merchant].filter(Boolean).join(" · ");
      const detail = document.createElement("span");
      detail.textContent = !drafts.matches(record.scope, scope) ? "旧浏览器身份，待核对" :
        record.phase === "submitted" ? "保存结果待确认" : record.phase === "blocked" ? "待核对" : "未提交";
      item.append(link, detail);
      list.appendChild(item);
    });
    shelf.querySelector("[data-manual-draft-count]").textContent = String(records.length);
    shelf.hidden = records.length === 0;
  }

  function persist(nextPhase) {
    if (retained && !drafts.read(currentRef)) throw Error("draft_removed");
    const record = drafts.save(scope, currentRef, nextPhase, values());
    retained = true;
    window.history.replaceState(null, "", "#manual-" + currentRef);
    return record;
  }

  function fragmentRef() {
    const match = /^#manual-([a-f0-9]{32})$/.exec(window.location.hash);
    return match ? match[1] : null;
  }

  function activate(ref, mustExist) {
    const turn = ++epoch;
    if (release) release();
    held = false;
    release = null;
    posting = false;
    fields.disabled = true;
    submit.disabled = true;
    notice("正在打开草稿…", "opening");
    window.navigator.locks.request(drafts.key(ref), {ifAvailable: true}, function (lock) {
      if (turn !== epoch) return;
      if (!lock) {
        fields.disabled = true;
        actions.hidden = false;
        notice("这一笔正在另一个标签页编辑。请回到那个页面，或另记一笔。", "locked");
        return;
      }
      held = true;
      currentRef = ref;
      refInput.value = ref;
      const record = drafts.read(ref);
      retained = !!record;
      if (!record && mustExist) {
        blocked("这份草稿已收起或已被移除。请先核对流水；需要时另记一笔。");
      } else if (record && !drafts.matches(record.scope, scope)) {
        if (drafts.matches(record.scope, scope, false)) {
          showValues(record.values);
          blocked("浏览器身份已更新。这是旧身份的草稿，仅供核对，不会换成新身份重提。");
        } else {
          blocked("这份草稿属于其他账号、账本或数据版本，不能在这里继续。");
        }
      } else {
        phase = record ? record.phase : "editing";
        // A fresh native GET has re-admitted the current writer. A previously
        // refused command may be retried unchanged, never edited into a new one.
        if (phase === "blocked" && !nativeResult) phase = "submitted";
        if (ref === nativeRef && nativeResult === "rejected") {
          showValues(nativeValues);
          drafts.save(scope, ref, "editing", nativeValues, "rejected");
          retained = true;
          phase = "editing";
        } else if (record) {
          showValues(record.values);
        }
        if (ref === nativeRef && nativeResult === "blocked") {
          phase = "blocked";
          // A native rejected POST can carry an old Device/ledger with no local
          // record. Do not manufacture a current-binding draft from that body.
          if (record) drafts.save(scope, ref, phase, record.values);
        }
        showPhase(!!record);
      }
      nativeResult = "";
      return new Promise(resolve => { release = resolve; });
    }).catch(function () {
      if (turn !== epoch) return;
      held = false;
      blocked("浏览器草稿暂时无法读取，原有内容未被覆盖。请保留此页，检查浏览器存储后再试。");
    });
  }

  form.addEventListener("invalid", function (event) {
    if (options.contains(event.target)) options.open = true;
  }, true);
  options.open = options.dataset.startExpanded !== "false";
  options.querySelector("summary").hidden = false;

  try {
    scope = JSON.parse(form.dataset.manualDraftScope);
    renderShelf();
    if (!window.navigator.locks) throw Error("locking_unavailable");
  } catch (_) {
    if (fragmentRef() || nativeResult === "blocked") {
      blocked("此浏览器暂不能安全打开保留的草稿。请先核对流水，或另开表单记账。");
    } else {
      notice("此浏览器不能保留草稿，离开前请完成记账或复制输入。", "unavailable");
    }
    return;
  }

  form.addEventListener("input", function () {
    if (!held || phase !== "editing") return;
    try {
      persist("editing");
      notice("草稿已保留在此浏览器，尚未提交。", "editing");
    } catch (_) {
      notice("最新输入未能保留。请勿关闭此页；浏览器存储恢复后可继续提交。", "storage-error");
    }
  });

  form.addEventListener("submit", function (event) {
    if (!held || phase === "blocked" || posting) {
      event.preventDefault();
      return;
    }
    try {
      if (phase === "submitted") {
        const record = drafts.read(currentRef);
        if (!record || !drafts.matches(record.scope, scope)) throw Error("draft_missing");
        showValues(record.values);
      }
      persist("submitted");
      phase = "submitted";
      posting = true;
      readOnly(true);
      // Disabled selects are omitted from a native POST; keep the fixed currency
      // successful while the document leaves. No fetch or automatic retry.
      controls.forEach(control => { if (control.tagName === "SELECT") control.disabled = false; });
      submit.disabled = true;
      notice("正在保存这笔支出…", "submitting");
    } catch (_) {
      event.preventDefault();
      notice("提交内容未能保留，这次没有发送。请勿关闭此页，检查浏览器存储后再试。", "storage-error");
    }
  });

  window.addEventListener("pagehide", function () {
    ++epoch;
    held = false;
    fields.disabled = true;
    submit.disabled = true;
    if (release) release();
    release = null;
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      const requested = fragmentRef();
      activate(requested || currentRef, !!requested || retained);
    }
  });
  window.addEventListener("hashchange", function () {
    const ref = fragmentRef();
    if (ref && ref !== currentRef) activate(ref, true);
  });
  window.addEventListener("storage", function () {
    try { renderShelf(); } catch (_) { shelf.hidden = true; }
  });
  const requested = nativeResult ? null : fragmentRef();
  activate(requested || nativeRef, !!requested);
})(window, document);
