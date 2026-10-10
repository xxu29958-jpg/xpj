/* Progressive native-form consumer. The server remains the sole command owner. */
(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-manual-draft-scope]");
  if (!form) return;
  const drafts = window.TicketboxManualDrafts;
  const fields = form.querySelector("[data-manual-edit-fields]");
  const submit = form.querySelector("[data-manual-submit]");
  const status = form.querySelector("[data-manual-draft-status]");
  const result = form.querySelector("[data-manual-result]");
  const options = form.querySelector("[data-manual-options]");
  const actions = document.querySelector("[data-manual-draft-actions]");
  const shelf = document.querySelector("[data-manual-draft-shelf]");
  const controls = drafts.fields.map(name => form.elements.namedItem(name)).filter(Boolean);
  const omitted = new Set();
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
  const preview = window.TicketboxAttachmentEntry?.originalSelection(form);
  const original = preview && window.TicketboxManualOriginal ? form.querySelector("[data-manual-original]") : null;
  const file = form.querySelector("[data-manual-original-file]");
  const removeFile = form.querySelector("[data-manual-original-remove]");
  let selecting = false;
  let selectionFailed = false;

  function notice(message, state) {
    status.textContent = message;
    status.hidden = false;
    form.dataset.manualDraftState = state;
  }

  function values() {
    return Object.fromEntries(controls.filter(control => !omitted.has(control.name))
      .map(control => [control.name, control.value]));
  }

  const nativeValues = values();

  function showSummaries() {
    form.querySelectorAll("[data-manual-value]").forEach(output => {
      output.textContent = form.elements.namedItem(output.dataset.manualValue).value || "可选";
    });
    const time = form.querySelector("[data-manual-date-value]");
    const name = form.elements.namedItem("time_precision")?.value === "date_only" ? "user_local_date" : "spent_at";
    if (time) time.textContent = form.elements.namedItem(name).value.replace("T", " ") || "待填写";
  }

  function showValues(saved) {
    controls.forEach(control => {
      const value = saved[control.name] ?? "";
      control.value = value;
      if (control.type === "datetime-local" && control.value !== value) {
        control.type = "text";
        control.value = value;
      }
      const absent = drafts.optionalFields.includes(control.name) && saved[control.name] === undefined;
      if (absent) omitted.add(control.name); else omitted.delete(control.name);
      control.disabled = absent;
    });
    if (saved.note) options.open = true;
    showSummaries();
  }

  function readOnly(value) {
    controls.forEach(control => {
      if (control.tagName === "SELECT") control.disabled = value || omitted.has(control.name);
      else control.readOnly = value;
    });
    if (file) {
      file.disabled = removeFile.disabled = value || selecting;
      removeFile.hidden = !form.elements.namedItem("original_file").value;
    }
  }

  function blocked(message) {
    phase = "blocked";
    fields.disabled = false;
    readOnly(true);
    submit.disabled = true;
    actions.hidden = false;
    notice(message, "blocked");
  }

  function showPhase(record) {
    const restored = !!record;
    form.dataset.manualDraftRestored = String(restored);
    result.hidden = !restored;
    if (record) {
      const href = new URL(draftHref(record), window.location.href);
      window.history.replaceState(null, "", href);
      href.pathname += "/result";
      href.hash = "";
      href.searchParams.set("client_ref", record.clientRef);
      href.searchParams.set("draft_scope", JSON.stringify(record.scope));
      result.href = href.href;
    }
    const heading = document.querySelector("[data-manual-heading]");
    if (heading) heading.textContent = restored ? "上次的记录还在" : "记一笔";
    fields.disabled = false;
    readOnly(phase !== "editing");
    submit.disabled = phase === "blocked" || selecting || selectionFailed;
    submit.textContent = phase === "submitted" ? "继续原提交" : "记下这笔支出";
    actions.hidden = phase === "editing";
    if (phase === "submitted") {
      notice("还未确认保存结果。可以先查看结果；继续提交仍是原来这一笔。", "submitted");
    } else if (phase === "blocked") {
      notice("这份草稿暂不能提交，输入仍在。请先核对流水与当前账号、账本。", "blocked");
    } else {
      notice(restored ? "草稿已恢复，继续这一笔。" : "填写后自动保留在此浏览器。", "editing");
    }
  }

  function draftHref(record) {
    const saved = record.values;
    const parts = [];
    function add(name, value) {
      parts.push(encodeURIComponent(name) + "=" + encodeURIComponent(value));
    }
    const ledger = form.elements.namedItem("ledger_id");
    if (ledger && ledger.value) add("ledger_id", ledger.value);
    const series = saved.return_recurring_public_id || "";
    const month = saved.return_month || "";
    const recurring = saved.return_to === "recurring_occurrence" &&
      /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(series) &&
      /^\d{4}-(0[1-9]|1[0-2])$/.test(month);
    if (recurring) {
      add("return_to", "recurring_occurrence");
      add("return_recurring_public_id", series);
      add("return_month", month);
      for (const name of ["return_payment_month", "return_query"]) {
        if (saved[name]) add(name, saved[name]);
      }
      const payment = saved.return_payment_expense_id || "";
      if (/^[1-9]\d{0,9}$/.test(payment) && Number(payment) <= 2147483647) {
        add("return_payment_expense_id", payment);
      }
    }
    if (["confirmed", "pending"].includes(saved.return_to)) {
      add("return_to", saved.return_to);
      for (const name of ["return_month", "return_filter", "return_page", "return_tag", "return_query", "return_category", "return_home_currency_code"]) {
        if (saved[name]) add(name, saved[name]);
      }
    }
    return "/web/expenses/new" + (parts.length ? "?" + parts.join("&") : "") + "#manual-" + record.clientRef;
  }

  function renderShelf() {
    const records = drafts.list(scope);
    const list = shelf.querySelector("[data-manual-draft-list]");
    list.replaceChildren();
    records.forEach(record => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = draftHref(record);
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
    window.history.replaceState(null, "", draftHref(record));
    return record;
  }

  function fragmentRef() {
    const match = /^#manual-([a-f0-9]{32})$/.exec(window.location.hash);
    return match ? match[1] : null;
  }

  function showOriginal() {
    const metadata = form.elements.namedItem("original_file")?.value;
    if (!original) {
      if (metadata) blocked("原件工具暂未加载，原稿与图片仍保留。请重新打开此页再继续。");
      return;
    }
    const ref = currentRef, turn = epoch;
    original.querySelector("[data-manual-original-label]").textContent = metadata ? "已保留所选图片" : "没有小票也可以记账";
    original.open = !!metadata;
    void preview.show(async () => {
      try { return await window.TicketboxManualOriginal.read(scope, ref, metadata); }
      catch (error) {
        if (turn === epoch) {
          selectionFailed = true;
          submit.disabled = true;
          notice("所选原文件暂时无法读取。原稿仍保留，请恢复浏览器存储，或重新选择图片。", "storage-error");
        }
        throw error;
      }
    }, phase !== "editing");
  }

  async function selectOriginal(source) {
    if (!held || phase !== "editing" || selecting) return;
    const turn = epoch, ref = currentRef;
    selecting = true;
    readOnly(true);
    submit.disabled = true;
    notice("正在保留所选图片，请暂时留在此页…", "selecting");
    try {
      persist("editing");
      const metadata = source ? await window.TicketboxManualOriginal.retain(scope, ref, source) : "";
      if (turn !== epoch) return;
      form.elements.namedItem("original_file").value = metadata;
      omitted.delete("original_file");
      persist("editing");
      selectionFailed = false;
      file.value = "";
      showOriginal();
      notice("原稿与所选图片已保留，尚未提交。", "editing");
    } catch (_) {
      if (turn !== epoch) return;
      selectionFailed = true;
      notice("图片尚未保留，这次没有发送。请保留此页，检查浏览器存储或重新选择图片。", "storage-error");
    } finally {
      if (turn === epoch) {
        selecting = false;
        readOnly(phase !== "editing");
        submit.disabled = selectionFailed || phase === "blocked";
      }
    }
  }

  function activate(ref, mustExist) {
    const turn = ++epoch;
    if (release) release();
    held = false;
    release = null;
    posting = false;
    selecting = selectionFailed = false;
    preview?.show(async () => null, false);
    result.hidden = true;
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
          const rejectedValues = {...nativeValues, original_file: record?.values.original_file};
          showValues(rejectedValues);
          drafts.save(scope, ref, "editing", rejectedValues, "rejected");
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
        showPhase(record);
        showOriginal();
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
  form.querySelectorAll(".manual-expense-options").forEach(disclosure => {
    disclosure.open = disclosure.dataset.startExpanded !== "false";
  });
  showSummaries();

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
    showSummaries();
    if (!held || phase !== "editing" || selecting || selectionFailed) return;
    try {
      persist("editing");
      notice("草稿已保留在此浏览器，尚未提交。", "editing");
    } catch (_) {
      notice("最新输入未能保留。请勿关闭此页；浏览器存储恢复后可继续提交。", "storage-error");
    }
  });

  form.addEventListener("submit", function (event) {
    if (!held || phase === "blocked" || posting || selecting || selectionFailed) {
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
      controls.forEach(control => {
        if (control.tagName === "SELECT") control.disabled = omitted.has(control.name);
      });
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
  if (original) {
    original.hidden = false;
    file.addEventListener("change", () => { if (file.files[0]) void selectOriginal(file.files[0]); });
    removeFile.addEventListener("click", () => { void selectOriginal(null); });
    window.addEventListener("beforeunload", event => {
      if (selecting || selectionFailed) { event.preventDefault(); event.returnValue = ""; }
    });
  }
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
