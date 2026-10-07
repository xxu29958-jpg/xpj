/* Bound forms share draft leases and original command receipts. */
(function (window, document) {
  "use strict";
  const definitions = {
    goal: {label: "消费目标", list: "/web/goals", amount: "target_amount_yuan",
      create: ["ledger_id", "home_currency_code", "month", "name", "target_amount_yuan", "category"],
      edit: ["ledger_id", "home_currency_code", "month", "name", "target_amount_yuan", "category",
        "public_id", "expected_row_version", "return_category", "return_month"]},
    income: {label: "收入计划", list: "/web/income-plans", amount: "amount_yuan",
      create: ["ledger_id", "home_currency_code", "intent_month", "label", "source_type", "frequency",
        "income_month", "income_month_year", "income_month_number", "amount_yuan", "pay_day"],
      edit: ["ledger_id", "home_currency_code", "intent_month", "public_id", "expected_row_version",
        "label", "source_type", "frequency", "income_month", "amount_yuan", "pay_day"]},
  };
  function mount(form, definition) {
    const family = definition.family;
    const isGoal = family === "goal";
    const taskLabel = definition.label, listPath = definition.list;
    const commandRefField = definition.commandRefField || "idempotency_key";
    const selector = suffix => "[data-" + family + "-" + suffix + "]";
    const data = suffix => form.dataset[family + suffix];
    const uuid = definition.validRef || /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
    const createNames = definition.create, editNames = definition.edit;
    const planId = data("PlanId") || "";
    const names = planId ? editNames : createNames;
    const createStore = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-create-draft:v1:",
      fields: [...createNames, "amount_placeholder", "amount_inputmode"], validRef: uuid});
    const editStore = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-edit-draft:v1:",
      fields: [...editNames, "amount_placeholder", "amount_inputmode"], validRef: uuid});
    const store = planId ? editStore : createStore;
    const anchor = "#" + family + (planId ? "-edit-" : "-create-");
    const reviewName = definition.reviewName || (planId ? "review_latest" : "review_new");
    const canWrite = data("CanWrite") !== "false";
    const archived = data("Archived") === "true";
    const editsAllowed = canWrite && !archived;
    const scope = JSON.parse(data("DraftScope"));
    const status = form.querySelector(selector("draft-status"));
    const submit = form.querySelector(definition.submitSelector || '[type="submit"]:not([name="review_new"]):not([name="review_latest"])');
    if (!submit) return;
    const nativeLabel = submit.textContent;
    const nativeRef = (definition.draftRefField && form.elements.namedItem(definition.draftRefField).value) || form.elements.namedItem(commandRefField).value;
    const amount = definition.amount ? form.elements.namedItem(definition.amount) : null;
    const shelf = document.querySelector(selector("draft-shelf"));
    const review = form.querySelector(selector("review"));
    const discard = form.querySelector(selector("discard"));
    const originalResult = form.querySelector(selector("original-result"));
    const permanentReadonly = new Set([...form.elements].filter(input => input.readOnly));
    const permanentDisabled = new Set([...form.elements].filter(input => input.matches(":disabled")));
    let ref = nativeRef, phase = "editing", held = false, retained = false, busy = false, accepted = false;
    let release = null, onlineOnly = false, blocked = false, reviewable = false;
    let leaseVersion = 0;

    function field(name) { return form.elements.namedItem(name); }
    function commandKey(record) { return definition.commandKeyField ? record.values[definition.commandKeyField] : ref; }
    function belongsToForm(record) { return !planId || record.values[definition.idField || "public_id"] === planId; }
    function freshHref() {
      if (definition.href) return definition.href(null, scope, form);
      const next = new URL(planId ? form.action : listPath, window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      next.searchParams.set("new_" + family, "1");
      if (isGoal) {
        for (const name of ["month", "return_category", "return_month"]) {
          if (field(name)?.value) next.searchParams.set(name, field(name).value);
        }
      } else if (planId) next.searchParams.set("intent_month", data("ReviewMonth"));
      if (!planId) next.hash = isGoal ? "new-goal" : "add-income";
      return next.href;
    }
    function recordHref(record) {
      if (definition.href) return definition.href(record, scope, form);
      const saved = record.values;
      const next = new URL(listPath + (saved.public_id ? "/" + encodeURIComponent(saved.public_id) + "/edit" : ""), window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      for (const name of isGoal ? ["month", "return_category", "return_month"] : ["intent_month"]) {
        if (saved[name]) next.searchParams.set(name, saved[name]);
      }
      next.hash = family + (saved.public_id ? "-edit-" : "-create-") + record.clientRef;
      return next.href;
    }
    function values() {
      return {...(definition.read ? definition.read(form) : Object.fromEntries(names.map(name => [name, field(name)?.value || ""]))),
        amount_placeholder: amount?.placeholder || "", amount_inputmode: amount?.inputMode || ""};
    }
    function notice(message) { status.hidden = false; status.textContent = message; }
    function fieldsEditable() {
      return editsAllowed && !blocked && phase === "editing" && (held || onlineOnly);
    }
    function commandAllowed() { return canWrite && (!archived || phase !== "editing"); }
    function actionUnavailable() { return blocked || busy || accepted || (!held && !onlineOnly); }
    function reviewAvailable() {
      if (!editsAllowed || blocked) return false;
      return phase === "editing" ? !!definition.reviewWhileEditing : !definition.reviewRequiresRejection || reviewable;
    }
    function usesDisabled(input) { return input.tagName === "SELECT" || ["checkbox", "radio"].includes(input.type); }
    function updateFields(editing) {
      [...form.elements].filter(input => names.includes(input.name) || definition.repeated?.includes(input.name)).forEach(input => {
        if (usesDisabled(input)) input.disabled = !editing || permanentDisabled.has(input);
        else input.readOnly = !editing || permanentReadonly.has(input);
      });
      form.querySelectorAll("[data-plan-preview], [data-budget-add-more], [data-command-review]").forEach(input => { input.disabled = !editing; });
    }
    function enableNativeValues() {
      [...form.elements].forEach(input => {
        if (usesDisabled(input)) input.disabled = permanentDisabled.has(input);
      });
    }
    function controls() {
      updateFields(fieldsEditable());
      submit.hidden = archived && phase === "editing";
      submit.disabled = !commandAllowed() || actionUnavailable();
      submit.textContent = phase === "editing" ? nativeLabel : definition.pendingLabel || "核实原" + taskLabel;
      review.hidden = !reviewAvailable();
      review.disabled = busy || accepted;
      discard.hidden = blocked || !retained;
      discard.disabled = busy || accepted || !held;
      if (originalResult) {
        originalResult.hidden = phase === "editing";
        originalResult.disabled = !commandAllowed() || actionUnavailable();
      }
      form.querySelector(selector("review-note")).hidden = review.hidden;
      form.dataset[family + "DraftPhase"] = phase;
      definition.updatePresentation?.(form, {phase, rejected: reviewable});
    }
    function stop(message) { blocked = true; controls(); notice(message); }
    function restoreFields(saved) {
      if (definition.restore) definition.restore(form, saved);
      else names.forEach(name => {
        let input = field(name);
        if (!input) {
          input = document.createElement("input");
          input.type = "hidden"; input.name = name; form.append(input);
        }
        if (input.tagName === "SELECT" && ![...input.options].some(option => option.value === saved[name])) {
          input.add(new Option(saved[name], saved[name]));
        }
        input.value = saved[name];
      });
      if (family === "income" && saved.income_month && field("income_month").type === "hidden") {
        const label = document.createElement("label");
        label.className = "product-field"; label.textContent = "原预计月份";
        field("income_month").type = "text";
        label.append(field("income_month"));
        form.querySelector("fieldset").prepend(label);
      }
      if (amount) {
        amount.placeholder = saved.amount_placeholder;
        amount.inputMode = saved.amount_inputmode;
      }
    }
    function restore(record) {
      if (!store.matches(record.scope, scope, false) || !belongsToForm(record)) {
        stop("这份原稿属于另一项任务，请从保留的" + taskLabel + "打开原任务。"); return false;
      }
      const saved = record.values;
      restoreFields(saved);
      if (definition.present) definition.present(form, saved);
      else form.querySelector(selector("amount-label")).textContent =
        (isGoal ? "目标金额（" : "预计金额（") + (saved.home_currency_code || "币种待确认") + "）";
      const intent = form.querySelector(selector("intent"));
      if (intent) intent.textContent = isGoal ?
        "本次目标属于 " + saved.month + "，失败重试保留原月份和金额。" :
        "本次每月计划从 " + (saved.intent_month || "待确认月份") + " 生效。失败重试保留原月份和金额。";
      phase = record.phase; reviewable = record.serverResult === "rejected";
      if (!definition.multiple) pointTo();
      if (!store.matches(record.scope, scope)) {
        stop("这是原浏览器身份的" + taskLabel + "，输入仍保留；不会转移到当前身份提交。"); return false;
      }
      field("draft_scope").value = JSON.stringify(record.scope);
      return true;
    }
    function pointTo() {
      // Reload must use the readable task address, including after a native review POST.
      // The same address also retains a void target absent from the current active list.
      const next = new URL(recordHref(store.read(ref)));
      const current = new URL(window.location.href);
      // A standard editor keeps its current read month beside the original intent month.
      if (!definition.href && next.pathname === current.pathname) next.search = current.search;
      if (definition.idField === "month") next.searchParams.set("month", field("month").value);
      next.hash = anchor + ref;
      window.history.replaceState(null, "", next.href);
    }
    function renderShelf() {
      const creates = createStore.list(scope), edits = editStore.list(scope);
      const records = (planId ? edits : creates).filter(belongsToForm);
      const list = shelf.querySelector(selector("draft-list"));
      list.replaceChildren();
      [...creates, ...edits].forEach(record => {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = recordHref(record);
        link.textContent = (record.values[definition.idField || "public_id"] ? "修改 · " : "新建 · ") + (record.values[definition.titleField || (isGoal ? "name" : "label")] || "未命名" + taskLabel) + " · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" :
            record.serverResult === "rejected" ? "已拒绝，待核对" : "结果待核对");
        item.append(link); list.append(item);
      });
      shelf.hidden = creates.length + edits.length === 0;
      return records;
    }
    function persist(nextPhase, serverResult = "") {
      const original = store.read(ref);
      if (retained && !original) throw Error("original_removed");
      if (values().ledger_id !== scope.ledgerId || !store.matches(JSON.parse(field("draft_scope").value), scope)) {
        throw Error("draft_binding_changed");
      }
      const record = store.save(scope, ref, nextPhase, values(), serverResult);
      retained = true; phase = nextPhase; pointTo(); renderShelf();
      return record;
    }
    function capture() {
      if (!editsAllowed || !held || busy || accepted || blocked || phase !== "editing") return;
      try { persist("editing"); controls(); notice("输入已保留在此浏览器，尚未提交。"); }
      catch (_) { notice("最新输入未能保留，请暂勿关闭此页；恢复浏览器存储后可继续提交。"); }
    }
    async function send() {
      const sentLease = leaseVersion;
      reviewable = false;
      const record = persist("submitted");
      controls();
      const body = new window.FormData();
      if (definition.body) definition.body(body, record.values);
      else names.forEach(name => body.set(name, record.values[name]));
      body.set("csrf_token", field("csrf_token").value);
      body.set("draft_scope", JSON.stringify(record.scope));
      body.set(commandRefField, commandKey(record));
      const response = await window.fetch(definition.action || form.action, {method: "POST", body, credentials: "same-origin",
        headers: {Accept: "application/json"}});
      const result = await response.json();
      if (!held || sentLease !== leaseVersion) throw Error("draft_lease_changed");
      if (!response.ok) {
        phase = "blocked";
        reviewable = result.draft_result === "rejected";
        store.save(scope, ref, phase, record.values, result.draft_result === "rejected" ? "rejected" : "");
        notice((result.message || "暂未确认提交结果。") + " 原稿仍保留，可沿原提交核实；需要修改时先核对当前记录。");
        return;
      }
      const next = receiptDestination(result, record);
      accepted = true;
      if (!store.acknowledge({...result.ack, clientRef: ref})) throw Error("original_not_acknowledged");
      notice(taskLabel + "已保存，正在返回…");
      window.location.assign(next.href);
    }
    function receiptDestination(result, record) {
      const receiptMatches = definition.receiptMatches ? definition.receiptMatches(result.receipt, record.values) :
        result.receipt?.public_id && (!planId || result.receipt.public_id === planId);
      if (!receiptMatches ||
          result.ack?.clientRef !== commandKey(record) || !store.matches(result.ack.scope, scope)) {
        throw Error("unconfirmed_receipt");
      }
      const next = new URL(result.next, window.location.href);
      const categoryReturn = (isGoal || family === "budget") && planId && record.values.return_category && next.pathname === "/web/categories";
      const destinationAllowed = definition.acceptsDestination ? definition.acceptsDestination(next, record.values) :
        next.pathname === listPath || categoryReturn;
      if (next.origin !== window.location.origin || !destinationAllowed ||
          next.searchParams.get("ledger_id") !== scope.ledgerId) throw Error("invalid_receipt_destination");
      return next;
    }
    form.addEventListener("input", capture);
    form.addEventListener("change", capture);
    originalResult?.addEventListener("click", () => {
      if (!commandAllowed() || actionUnavailable() || phase === "editing") return;
      const record = store.read(ref), body = new window.FormData();
      if (!record || !store.matches(record.scope, scope)) return;
      definition.body(body, record.values);
      body.set("csrf_token", field("csrf_token").value); body.set("draft_scope", JSON.stringify(record.scope));
      body.set("idempotency_key", commandKey(record));
      const native = document.createElement("form"); native.method = "post"; native.action = form.action;
      for (const [name, value] of body) {
        const input = document.createElement("input"); input.type = "hidden"; input.name = name; input.value = value; native.append(input);
      }
      document.body.append(native); busy = true; controls(); native.submit();
    });
    discard.addEventListener("click", () => {
      if (!held || busy || accepted || blocked) return;
      const message = phase === "editing" ? "放弃此浏览器保留的未提交输入？" :
        "请先核对已有" + taskLabel + "。此操作只移除本地原稿，不会撤销已发出的请求或保存结果。确认放弃原稿？";
      if (!window.confirm(message)) return;
      try {
        const record = store.read(ref);
        if (!record || !store.discardLocal({scope, clientRef: ref, values: record.values, decision: "discard-local"})) {
          throw Error("original_changed");
        }
        accepted = true; controls();
        window.location.assign(freshHref());
      } catch (_) { notice("原稿未能移除，请保留页面并检查浏览器存储。"); }
    });
    function allowNativeSubmission(submitter) {
      if (definition.relatedAction?.(submitter) && canWrite && held && !busy && !blocked) {
        enableNativeValues();
        return true;
      }
      if (submitter?.hasAttribute("data-plan-preview") && fieldsEditable() && !busy) {
        capture(); return true;
      }
      // The existing explicit review prepares a fresh form without submitting a plan.
      if (submitter?.name === reviewName && reviewAvailable() && held && !busy) {
        enableNativeValues();
        return true;
      }
      return false;
    }
    form.addEventListener("submit", async event => {
      if (onlineOnly || allowNativeSubmission(event.submitter)) return;
      event.preventDefault();
      if (!commandAllowed() || !held || busy || accepted || blocked) return;
      busy = true; controls(); notice("正在提交原" + taskLabel + "…");
      try { await send(); }
      catch (_) { notice(accepted ? taskLabel + "已保存，本地原稿暂未收起；请核对列表。" :
        "暂未收到保存回执。原稿仍保留，恢复连接后可核实原" + taskLabel + "。"); }
      finally { busy = false; controls(); renderShelf(); }
    });
    function allowOnline() {
      if (window.location.hash.startsWith(anchor) || retained) {
        stop("浏览器暂时无法安全恢复这份原稿。请恢复存储能力后继续，原稿不会被覆盖。");
        return;
      }
      onlineOnly = true; controls();
      notice("此浏览器无法持久保留输入，仍可在本页在线提交；关闭或刷新前请先保存。");
    }
    function activationNotice(record) {
      if (!canWrite) { notice(record ? "当前角色为只读，原稿仍保留；恢复编辑权限后可继续。" : "当前角色为只读，可核对已保存的记录。"); return; }
      if (archived && phase === "editing") { notice(definition.inactiveMessage || (record ? "计划已归档，原输入仍保留；请先恢复计划再核对修改。" : "计划已归档，请先恢复计划再修改。")); return; }
      if (record && phase !== "editing" && reviewable) {
        notice("服务器已拒绝这次原提交，原输入仍保留。核对当前记录后，可保留输入继续修改。"); return;
      }
      notice(record ? phase === "editing" ? "已恢复原" + taskLabel + "，保留原输入和版本依据。" :
        "原提交结果尚未确认。核实会沿用原内容和编号。" : "输入会保留在此浏览器，尚未提交。");
    }
    function selectDraft(records, nativeResult) {
      let wanted = window.location.hash.startsWith(anchor) ? window.location.hash.slice(anchor.length) : "";
      if (definition.multiple && wanted && !belongsToForm(store.read(wanted) || {values: {}})) wanted = "";
      const separateNewForm = data("NewDraft") === "true";
      if (separateNewForm) wanted = "";
      const explicitNew = separateNewForm || new URL(window.location.href).searchParams.get("new_" + family) === "1";
      const preferred = records.find(record => record.phase !== "editing") || records[0];
      return {wanted, ref: nativeResult ? nativeRef : wanted || (!explicitNew && preferred ? preferred.clientRef : nativeRef)};
    }
    function applyNativeResult(record, nativeResult) {
      if (!record) {
        if (["blocked", "rejected"].includes(nativeResult)) {
          phase = "blocked"; reviewable = nativeResult === "rejected";
        }
        return true;
      }
      const originalRejected = nativeResult === "rejected" &&
        field(commandRefField).value === commandKey(record) &&
        store.matches(JSON.parse(field("draft_scope").value), record.scope);
      if (nativeResult === "prepared" && (record.serverResult === "rejected" ||
          (definition.reviewWhileEditing && record.phase === "editing"))) {
        store.save(scope, ref, "editing", values(), "rejected");
        phase = "editing"; pointTo();
      } else {
        if (!restore(record)) return false;
        if (originalRejected) {
          phase = "blocked"; reviewable = true;
          store.save(scope, ref, phase, record.values, "rejected");
        }
      }
      if (nativeResult) renderShelf();
      return true;
    }
    function resumeDraft(record, nativeResult) {
      if (!applyNativeResult(record, nativeResult)) return false;
      if (!store.matches(JSON.parse(field("draft_scope").value), scope)) {
        stop("身份或账本已切换，原输入仍保留；请恢复原身份后继续。"); return false;
      }
      if (!record && nativeResult) persist(phase, nativeResult === "rejected" ? "rejected" : "");
      if (record && definition.multiple && form.closest("details")) {
        form.closest("details").hidden = false; form.closest("details").open = true;
      }
      controls();
      activationNotice(record);
      return true;
    }
    function activate() {
      const currentLease = ++leaseVersion;
      blocked = false; controls();
      if (!window.navigator.locks) { allowOnline(); return; }
      try {
        const nativeResult = data("NativeResult");
        const selected = selectDraft(renderShelf(), nativeResult);
        const wanted = selected.wanted;
        ref = selected.ref;
        if (!uuid.test(ref)) { stop("原稿编号无法核对，请从保留的" + taskLabel + "重新打开。"); return; }
        window.navigator.locks.request(store.key(ref), {ifAvailable: true}, async lock => {
          if (currentLease !== leaseVersion) return;
          if (!lock) { stop("这份原稿正在另一标签页使用。关闭那一页后，重新打开即可继续。"); return; }
          const record = store.read(ref);
          if (!record && (retained || (wanted && !nativeResult))) { stop("原稿已收起，请先核对" + taskLabel + "列表。"); return; }
          retained = !!record;
          held = true;
          if (!definition.commandKeyField) field(commandRefField).value = ref;
          if (definition.draftRefField) field(definition.draftRefField).value = ref;
          if (!resumeDraft(record, nativeResult)) return;
          return new Promise(resolve => { release = resolve; });
        }).catch(() => { if (!held) allowOnline(); else stop("原稿暂时无法恢复，请保留此页并检查浏览器存储。"); });
      } catch (_) { allowOnline(); }
    }
    window.addEventListener("pagehide", () => { leaseVersion += 1; held = false; if (release) release(); release = null; });
    window.addEventListener("pageshow", event => { if (event.persisted && !accepted) activate(); });
    window.addEventListener("hashchange", () => {
      if (window.location.hash.startsWith(anchor)) window.location.reload();
    });
    activate();
  }
  window.TicketboxPlanEntry = {mount};
  for (const [family, definition] of Object.entries(definitions)) {
    document.querySelectorAll("[data-" + family + "-draft-scope]").forEach(form => mount(form, {...definition, family}));
  }
})(window, document);
