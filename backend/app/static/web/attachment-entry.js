/* One explicit native-form continuation for uploads and original commands. */
(function (window, document) {
  "use strict";
  const drafts = window.TicketboxAttachmentDrafts;
  const store = drafts.store;
  function originalSelection(form) {
    const image = form.querySelector("[data-attachment-selected-image]");
    if (!image) return null;
    const check = form.querySelector("[data-attachment-selected-check]");
    const reviewLabel = form.querySelector("[data-attachment-selected-label]");
    const open = form.querySelector("[data-attachment-selected-open]");
    const status = form.querySelector("[data-attachment-selection-status]");
    let imageUrl;
    let revision = 0;
    function reviewState(checked, disabled, external = false) {
      if (!check) return;
      check.checked = checked;
      check.disabled = disabled;
      reviewLabel.textContent = external ? "我已在图片应用核对原文件，确认它属于这笔账单" : "这是这笔账单对应的原件";
    }
    reviewState(false, true);
    open.addEventListener("click", () => { if (check && form.dataset.attachmentPhase === "editing") check.disabled = false; });
    window.addEventListener("pagehide", () => { if (imageUrl) window.URL.revokeObjectURL(imageUrl); });
    return {
      needsReview: () => !!check && !check.checked,
      freeze() { reviewState(true, true); },
      async show(source, fixed) {
        const turn = ++revision;
        reviewState(fixed, true);
        image.hidden = true;
        open.hidden = true;
        if (imageUrl) window.URL.revokeObjectURL(imageUrl);
        imageUrl = null;
        status.textContent = "正在打开所选图片…";
        let file;
        try {
          file = await source();
          if (turn !== revision) return;
          if (!file) { status.textContent = "选择图片后，先预览再确认。"; return; }
          imageUrl = window.URL.createObjectURL(file);
          open.href = imageUrl;
          open.download = file.name;
          const imageSource = await window.TicketboxDraftFiles.imageSource(file);
          if (turn !== revision) return;
          image.src = imageSource;
          await image.decode();
          if (turn !== revision) return;
          image.hidden = false;
          reviewState(fixed, fixed);
          status.textContent = file.name + (!check ? " · 账单保存后继续确认关联。" : fixed ? " · 已提交的原文件；重试仍使用此文件。" : " · 请核对图片是否属于这笔账单。");
        } catch (_) {
          if (turn !== revision) return;
          if (file && imageUrl) {
            open.hidden = false;
            reviewState(fixed, true, true);
            status.textContent = fixed ? "浏览器无法显示原文件；重试仍使用已确认的文件。" :
              "浏览器无法打开这张图片。请下载原文件，在图片应用中查看后再确认；也可以重新选择。";
          } else { status.textContent = "原文件暂时无法读取，尚未发送。请恢复浏览器存储后继续原任务。"; }
        }
      },
    };
  }
  function shelf(scope) {
    const host = document.querySelector("[data-attachment-shelf]");
    if (!host) return;
    host.replaceChildren();
    store.list(scope).forEach(record => {
      if (host.hasAttribute("data-capture-originals") && new URL(record.values.action).pathname === "/web/pending/upload") return;
      const link = document.createElement("a");
      link.href = drafts.taskPage(record.values.action) + "#attachment-" + record.clientRef;
      link.textContent = (record.values.file_name || "原件核对任务") +
        (store.matches(record.scope, scope) ? " · 继续原任务" : " · 旧浏览器身份，保留待核对");
      const item = document.createElement("p");
      item.append(link);
      host.append(item);
    });
    if (host.hasAttribute("data-capture-originals")) host.hidden = !host.childElementCount;
  }
  function init(form, options = {}) {
    const wanted = options.batch ? null : /^#attachment-([a-f0-9]{32})$/.exec(window.location.hash);
    const scope = JSON.parse(form.dataset.attachmentScope);
    const status = form.querySelector("[data-attachment-status]");
    const file = form.elements.namedItem("file");
    const button = form.querySelector('[type="submit"]');
    const label = button.textContent;
    const selection = originalSelection(form);
    let ref = form.dataset.attachmentRef;
    let held = false;
    let release;
    let busy = false;
    let accepted = false;
    let captureError = false;
    let onlineOnly = false;
    let retained = false;
    let rejection = null;
    const discard = document.createElement("button");
    discard.type = "button";
    discard.className = "product-button product-button--quiet";
    discard.textContent = "丢弃已拒绝任务";
    discard.hidden = true;
    discard.dataset.attachmentDiscard = "";
    status.after(discard);
    discard.addEventListener("click", async () => {
      if (!held || busy || accepted || !rejection ||
          !window.confirm("服务器已拒绝此任务。确定丢弃浏览器内的原请求和所选文件？此操作无法恢复。")) return;
      busy = true;
      discard.disabled = true;
      button.disabled = true;
      try {
        if (!await drafts.discardRejected(rejection)) throw Error("draft_binding_changed");
        accepted = true;
        discard.hidden = true;
        notice("已丢弃此任务和本地文件；请重新打开表单选择文件。");
        shelf(scope);
        if (options.onDiscarded) { held = false; release?.(); options.onDiscarded(); }
      } catch (_) { notice("任务未能完整清理，请保留页面并检查浏览器存储。"); }
      finally { busy = false; discard.disabled = false; changed(); }
    });
    function changed() { options.onChange?.(); }
    function needsOriginalReview() {
      if ((form.dataset.attachmentPhase || "editing") !== "editing") return false;
      return !!selection?.needsReview() || (form.hasAttribute("data-original-verification") &&
        !form.elements.namedItem("reviewed_sha256").value);
    }
    function notice(text) { status.textContent = text; changed(); }
    function allowOnlineOnly() {
      if (wanted || retained || accepted) return false;
      try { if (store.read(ref)) return false; }
      catch (_) { /* Only this fresh server-issued form may use native submission. */ }
      onlineOnly = true;
      form.dataset.attachmentPhase = "editing";
      button.disabled = needsOriginalReview();
      selection?.show(async () => file?.files[0], false).then(() => { button.disabled = needsOriginalReview(); });
      button.textContent = label + "（仅当前页在线提交）";
      notice(options.batch ? "原图未能保留，离开后无法恢复此选择。" : "浏览器未能持久保存文件；仍可在本页在线提交。离开或重载后不能恢复所选文件，请先确认网络可用。");
      options.onReady?.();
      return true;
    }
    function controls(record) {
      const fixed = !!record && record.phase !== "editing";
      form.dataset.attachmentPhase = record?.phase || "editing";
      if (file) { file.disabled = fixed || busy; file.required = !record?.values.file_sha256; }
      if (fixed) selection?.freeze();
      button.textContent = fixed ? "重试原任务" : label + (onlineOnly ? "（仅当前页在线提交）" : "");
      for (const name of ["reviewed_sha256", "request_id"]) {
        const input = form.elements.namedItem(name);
        if (input) input.readOnly = fixed;
      }
      const reviewed = form.querySelector("[data-original-reviewed]");
      if (fixed && record?.values.reviewed_sha256 && reviewed) {
        reviewed.checked = true;
        reviewed.disabled = true;
      }
    }
    function values() {
      const previous = store.read(ref);
      return {action: form.action,
        request_id: form.elements.namedItem("request_id")?.value || "", file_sha256: "", file_name: "",
        file_type: "", file_last_modified: "", ...(previous?.values || {}),
        reviewed_sha256: form.elements.namedItem("reviewed_sha256")?.value || ""};
    }
    async function capture() {
      if (!held || busy || accepted) return;
      let record = store.read(ref);
      if (record && record.phase !== "editing") return;
      busy = true;
      button.disabled = true;
      controls(record);
      notice("正在保留原文件和任务，请暂勿关闭此页…");
      try {
        record = await drafts.retain(scope, ref, values(), file?.files[0]);
        retained = true;
        await selection?.show(async () => (await drafts.readSource(scope, ref)).file, false);
        captureError = false;
        if (!options.batch) window.history.replaceState(null, "", "#attachment-" + ref);
        notice(options.batch ? "原图已保留 · 准备上传" : (record.values.file_name || "原件任务") + " 已保留在此浏览器，尚未提交。");
        shelf(scope);
      } catch (error) {
        captureError = true;
        if (error.message === "upload_too_large") {
          onlineOnly = false;
          notice("所选文件超过服务器上传上限，请选择较小文件；本次不会读取或发送该文件。");
          return;
        }
        if (!allowOnlineOnly()) notice("最新文件未能保留，本次不会发送。原任务仍在；请保留页面，或重新检查后另开表单选择。");
      } finally {
        busy = false;
        controls(record);
        if (!onlineOnly) button.disabled = !held || captureError || needsOriginalReview();
        changed();
      }
    }
    async function send() {
      rejection = null;
      discard.hidden = true;
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
        if (["state_conflict", "image_replenishment_mismatch", "original_replenishment_not_needed", "original_already_associated"].includes(result.error)) {
          rejection = {scope, clientRef: ref, values: record.values, serverResult: "rejected"};
          discard.hidden = false;
        }
        notice((result.message || "提交未完成。") + " 原文件与原请求保留；可重试原任务，或先核对当前账单。");
        return;
      }
      if (!result.receipt || result.ack?.clientRef !== ref || !store.matches(result.ack.scope, scope)) {
        throw Error("unconfirmed_receipt");
      }
      accepted = true;
      try { await drafts.acknowledge(result.ack); }
      finally { options.onAccepted?.(result); }
      notice("操作已接受，正在返回原账单…");
      if (!options.batch) window.location.assign(result.next);
    }
    form.addEventListener("change", event => {
      if (event.target.hasAttribute("data-attachment-selected-check")) {
        button.disabled = busy || !held && !onlineOnly || accepted || captureError && !onlineOnly || needsOriginalReview();
      } else { void capture(); }
    });
    function canSubmitRetained() {
      return !onlineOnly && held && !busy && !accepted && !captureError && !needsOriginalReview();
    }
    async function submit() {
      if (!canSubmitRetained()) return false;
      const record = store.read(ref);
      if (!record || record.phase === "editing" && !selection) await capture();
      if (!canSubmitRetained()) return false;
      busy = true;
      button.disabled = true;
      notice("正在提交原任务…");
      try { await send(); }
      catch (_) { notice(accepted ? "操作已接受，本地文件暂未收起。请返回原账单，不要再次提交。" :
        "暂未收到保存回执。原文件和原请求仍在；恢复连接后重试原任务。"); }
      finally { busy = false; button.disabled = accepted || !held || needsOriginalReview(); shelf(scope); changed(); }
      return accepted;
    }
    form.addEventListener("submit", event => {
      if (onlineOnly) { if (needsOriginalReview()) event.preventDefault(); return; }
      event.preventDefault();
      void submit();
    });
    function restoreForm(record) {
      form.hidden = false;
      if (!options.batch) form.closest("details")?.setAttribute("open", "");
      form.action = record.values.action;
      for (const name of ["reviewed_sha256", "request_id"]) {
        if (form.elements.namedItem(name)) form.elements.namedItem(name).value =
          name === "reviewed_sha256" && record.phase === "editing" ? "" : record.values[name];
      }
      notice(options.batch ? "原图与原请求已恢复" : (record.values.file_name || "原件任务") + " 已恢复；提交沿用原文件、版本与请求。");
    }
    function activate() {
      if (!form.isConnected) return;
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
          notice("请选择小票图片。上传后仍需核对确认。");
        }
        controls(record);
        if (selection) {
          file.disabled = true;
          await selection.show(async () => record ? (await drafts.readSource(scope, ref)).file : null,
            !!record && record.phase !== "editing");
          controls(record);
        }
        button.disabled = (!record && form.dataset.attachmentAvailable === "false") ||
          needsOriginalReview();
        options.onReady?.();
        changed();
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
    return {
      submit, capture,
      state: () => ({busy, accepted, onlineOnly, ready: held && !busy && !accepted && !captureError,
        canRemove: held && !busy && !accepted && (form.dataset.attachmentPhase || "editing") === "editing",
        phase: form.dataset.attachmentPhase || "editing"}),
      async remove() {
        if (!held || busy || accepted) return false;
        busy = true;
        try {
          if (!await drafts.discardEditing(scope, ref)) return false;
          held = false;
          release?.();
          return true;
        } finally { busy = false; changed(); }
      },
    };
  }
  window.TicketboxAttachmentEntry = {init, shelf, originalSelection};
  document.querySelectorAll("[data-attachment-scope]:not([data-inbox-batch])").forEach(form => {
    try { init(form, {onReady: () => form.dispatchEvent(new Event("attachment-ready"))}); }
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
