/* One explicit native-form continuation for uploads and original commands. */
(function (window, document) {
  "use strict";
  const drafts = window.TicketboxAttachmentDrafts;
  const store = drafts.store;
  const wanted = /^#attachment-([a-f0-9]{32})$/.exec(window.location.hash);
  function taskPage(action) {
    const url = new URL(action, window.location.href);
    const path = url.pathname === "/web/pending/upload" ? "/web/pending" :
      url.pathname.replace(/\/original\/(verify|replenish|cleanup\/(retry|cancel))$/, "/original");
    return path + "?ledger_id=" + encodeURIComponent(url.searchParams.get("ledger_id"));
  }
  function shelf(scope) {
    const host = document.querySelector("[data-attachment-shelf]");
    if (!host) return;
    host.replaceChildren();
    store.list(scope).forEach(record => {
      const link = document.createElement("a");
      link.href = taskPage(record.values.action) + "#attachment-" + record.clientRef;
      link.textContent = (record.values.file_name || "原件核对任务") +
        (store.matches(record.scope, scope) ? " · 继续原任务" : " · 旧浏览器身份，保留待核对");
      const item = document.createElement("p");
      item.append(link);
      host.append(item);
    });
  }
  function init(form) {
    const scope = JSON.parse(form.dataset.attachmentScope);
    const status = form.querySelector("[data-attachment-status]");
    const file = form.elements.namedItem("file");
    const button = form.querySelector('[type="submit"]');
    const label = button.textContent;
    let ref = form.dataset.attachmentRef;
    let held = false;
    let release;
    let busy = false;
    let accepted = false;
    let captureError = false;
    let onlineOnly = false;
    let retained = false;
    function notice(text) { status.textContent = text; }
    function allowOnlineOnly() {
      if (wanted || retained || accepted) return false;
      try { if (store.read(ref)) return false; }
      catch (_) { /* Only this fresh server-issued form may use native submission. */ }
      onlineOnly = true;
      button.disabled = form.hasAttribute("data-original-verification") &&
        !form.elements.namedItem("reviewed_sha256").value;
      button.textContent = label + "（仅当前页在线提交）";
      notice("浏览器未能持久保存文件；仍可在本页在线提交。离开或重载后不能恢复所选文件，请先确认网络可用。");
      return true;
    }
    function controls(record) {
      const fixed = !!record && record.phase !== "editing";
      form.dataset.attachmentPhase = record?.phase || "editing";
      if (file) { file.disabled = fixed; file.required = !record?.values.file_sha256; }
      button.textContent = fixed ? "重试原任务" : label;
      for (const name of ["reviewed_sha256", "request_id"]) {
        const input = form.elements.namedItem(name);
        if (input) input.readOnly = fixed;
      }
      const reviewed = form.querySelector("[data-original-reviewed]");
      if (record?.values.reviewed_sha256 && reviewed) {
        reviewed.checked = true;
        reviewed.disabled = true;
      }
    }
    function values() {
      const previous = store.read(ref);
      return {action: form.action, reviewed_sha256: form.elements.namedItem("reviewed_sha256")?.value || "",
        request_id: form.elements.namedItem("request_id")?.value || "", file_sha256: "", file_name: "",
        file_type: "", file_last_modified: "", ...(previous?.values || {})};
    }
    async function capture() {
      if (!held || busy || accepted) return;
      const record = store.read(ref);
      if (record && record.phase !== "editing") return;
      busy = true;
      button.disabled = true;
      notice("正在保留原文件和任务，请暂勿关闭此页…");
      try {
        const raw = values();
        raw.reviewed_sha256 = form.elements.namedItem("reviewed_sha256")?.value || "";
        const saved = await drafts.retain(scope, ref, raw, file?.files[0]);
        retained = true;
        controls(saved);
        captureError = false;
        window.history.replaceState(null, "", "#attachment-" + ref);
        notice((saved.values.file_name || "原件任务") + " 已保留在此浏览器，尚未提交。");
        shelf(scope);
      } catch (_) {
        captureError = true;
        if (!allowOnlineOnly()) notice("最新文件未能保留，本次不会发送。原任务仍在；请保留页面，或重新检查后另开表单选择。");
      } finally { busy = false; if (!onlineOnly) button.disabled = !held || captureError; }
    }
    async function send() {
      const {record, file: savedFile} = await drafts.submitted(scope, ref);
      controls(record);
      const body = new window.FormData();
      body.set("csrf_token", form.elements.namedItem("csrf_token").value);
      for (const name of ["reviewed_sha256", "request_id"]) {
        if (record.values[name]) body.set(name, record.values[name]);
      }
      if (savedFile) body.set("file", savedFile, record.values.file_name);
      const response = await window.fetch(record.values.action,
        {method: "POST", body, headers: {Accept: "application/json"}, credentials: "same-origin"});
      const result = await response.json();
      if (!response.ok) {
        store.save(scope, ref, "blocked", record.values);
        notice((result.message || "提交未完成。") + " 原文件与原请求保留；可重试原任务，或先核对当前账单。");
        return;
      }
      if (!result.receipt || result.ack?.clientRef !== ref || !store.matches(result.ack.scope, scope)) {
        throw Error("unconfirmed_receipt");
      }
      accepted = true;
      await drafts.acknowledge(result.ack);
      notice("操作已接受，正在返回原账单…");
      window.location.assign(result.next);
    }
    form.addEventListener("change", capture);
    form.addEventListener("submit", async event => {
      if (onlineOnly) return;
      event.preventDefault();
      if (!held || busy || accepted || captureError) return;
      if (!store.read(ref)) await capture();
      if (captureError || !held) return;
      busy = true;
      button.disabled = true;
      notice("正在提交原任务…");
      try { await send(); }
      catch (_) { notice(accepted ? "操作已接受，本地文件暂未收起。请返回原账单，不要再次提交。" :
        "暂未收到保存回执。原文件和原请求仍在；恢复连接后重试原任务。"); }
      finally { busy = false; button.disabled = accepted || !held; shelf(scope); }
    });
    function restoreForm(record) {
      form.hidden = false;
      form.action = record.values.action;
      for (const name of ["reviewed_sha256", "request_id"]) {
        if (form.elements.namedItem(name)) form.elements.namedItem(name).value = record.values[name];
      }
      notice((record.values.file_name || "原件任务") + " 已恢复；提交沿用原文件、版本与请求。");
    }
    function activate() {
      button.disabled = true;
      if (!window.navigator.locks || !window.indexedDB) {
        if (!allowOnlineOnly()) notice("浏览器不能安全恢复原任务；原文件仍保留，请恢复存储能力后继续。");
        return;
      }
      let record;
      if (wanted) {
        record = store.read(wanted[1]);
        if (!record) { notice("原任务已收起；请先核对账单，不会重新提交。"); return; }
        if (new URL(record.values.action).pathname !== new URL(form.action).pathname) return;
        ref = wanted[1];
      }
      window.navigator.locks.request(store.key(ref), {ifAvailable: true}, async lock => {
        if (!lock) { notice("原任务已在另一个标签页打开。"); return; }
        record = store.read(ref);
        if (accepted || (retained && !record)) {
          notice("原任务已收起；请先核对账单，不会重新提交。");
          return;
        }
        retained = retained || !!record;
        if (record && !store.matches(record.scope, scope)) {
          notice("原任务属于旧身份或其他账本，文件仍保留；请恢复原身份后继续。");
          return;
        }
        held = true;
        accepted = false;
        if (record) {
          restoreForm(record);
        } else if (form.hasAttribute("data-inbox-capture")) {
          const url = new URL(form.action);
          url.searchParams.set("timezone", Intl.DateTimeFormat().resolvedOptions().timeZone || "");
          form.action = url.href;
        }
        controls(record);
        button.disabled = (!record && form.dataset.attachmentAvailable === "false") ||
          (form.hasAttribute("data-original-verification") && !record?.values.reviewed_sha256);
        return new Promise(resolve => { release = resolve; });
      }).catch(() => {
        if (!allowOnlineOnly()) notice("浏览器不能安全恢复原任务；已有文件未被覆盖，请恢复存储能力后继续。");
      });
    }
    window.addEventListener("pagehide", () => {
      held = false;
      button.disabled = true;
      if (release) release();
    });
    window.addEventListener("pageshow", event => { if (event.persisted) activate(); });
    try { shelf(scope); }
    catch (_) {
      button.disabled = true;
      if (!allowOnlineOnly()) notice("浏览器不能安全恢复原任务；已有文件未被覆盖，请恢复存储能力后继续。");
      return;
    }
    activate();
  }
  document.querySelectorAll("[data-attachment-scope]").forEach(form => {
    try { init(form); }
    catch (_) { form.querySelector("[data-attachment-status]").textContent = "原任务无法读取，请保留页面并核对浏览器存储。"; }
  });
  window.addEventListener("hashchange", () => {
    if (/^#attachment-[a-f0-9]{32}$/.test(window.location.hash)) window.location.reload();
  });
  // The established loopback native upload keeps its device-free capability.
  const local = document.querySelector("[data-inbox-capture]:not([data-attachment-scope])");
  if (local) {
    const url = new URL(local.action);
    url.searchParams.set("timezone", Intl.DateTimeFormat().resolvedOptions().timeZone || "");
    local.action = url.href;
  }
})(window, document);
