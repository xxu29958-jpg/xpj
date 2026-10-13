/* Compose image rows over the existing per-file attachment intent controller.
 * This list is a view; original files, keys and unknown replies stay with that owner. */
(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-inbox-batch]");
  if (!form) return;
  const entry = window.TicketboxAttachmentEntry;
  if (!form.dataset.attachmentScope) { nativePreview(form); return; }
  if (!window.navigator.locks || !window.indexedDB || !window.crypto.randomUUID) {
    entry.init(form);
    nativePreview(form);
    return;
  }
  const scope = JSON.parse(form.dataset.attachmentScope);
  const drafts = window.TicketboxAttachmentDrafts;
  const task = form.closest("[data-inbox-upload]");
  const picker = form.elements.namedItem("file");
  const submit = form.querySelector('[type="submit"]');
  const status = form.querySelector("[data-attachment-status]");
  const selection = task.querySelector("[data-capture-selection]");
  const host = task.querySelector("[data-capture-items]");
  const footer = task.querySelector("[data-capture-actions]");
  const shelf = task.querySelector("[data-attachment-shelf]");
  shelf.dataset.captureOriginals = "";
  const stop = document.createElement("button");
  stop.type = "button";
  stop.className = "product-button product-button--quiet";
  stop.textContent = "停止后续上传";
  stop.hidden = true;
  footer.prepend(submit, stop);
  submit.setAttribute("form", form.id);
  picker.multiple = true;
  picker.required = false;
  task.querySelector("[data-capture-picker-hint]").textContent = "支持一次选择多张小票";
  const items = [];
  let sending = false;
  let stopped = false;
  let attempted = false;
  let closedTask = false;
  function update() {
    const accepted = items.filter(item => item.result).length;
    selection.hidden = items.length === 0;
    task.querySelector("[data-capture-count]").textContent = items.length + " 张";
    const ready = items.filter(item => !item.result && item.controller?.state().ready && !item.controller.state().onlineOnly);
    const preparing = !sending && items.some(item => item.controller?.state().busy);
    const onlineOnly = items.some(item => item.controller?.state().onlineOnly);
    submit.hidden = onlineOnly && !ready.length && !accepted;
    submit.disabled = closedTask || sending || preparing || (!ready.length && !accepted);
    submit.textContent = sending ? "正在上传…" : preparing ? "正在保留原图…" : ready.length ? (attempted ? "继续上传 " : "上传 ") + ready.length + " 张小票" :
      accepted ? "返回收件箱核对" : "上传小票";
    picker.disabled = closedTask || sending;
    if (onlineOnly) status.textContent = "浏览器不能保留这些原图。请逐张在线上传，离开会失去尚未上传的选择。";
    form.querySelector(".file-picker").hidden = attempted;
    stop.hidden = !sending;
    updateProgress(accepted);
    items.forEach(updateRow);
  }
  function updateProgress(accepted) {
    task.querySelector("[data-capture-progress]").hidden = !attempted && !accepted;
    task.querySelector("[data-capture-progress-label]").textContent = accepted + " / " + items.length;
    const progress = task.querySelector("[data-capture-progress-bar]");
    progress.max = Math.max(1, items.length);
    progress.value = accepted;
    if (accepted) {
      const readyToReview = accepted === items.length && items.every(item => item.recognition === "updated");
      task.querySelector("[data-capture-title]").textContent = readyToReview ? "小票已准备好核对" : "小票正在整理";
      task.querySelector("[data-capture-description]").textContent = readyToReview ? "核对金额、商家和日期，确认后计入流水。" : "已收到的图片会继续识别，可以离开后再回来。";
      task.querySelector("[data-capture-progress] .product-page-summary").textContent = readyToReview ? "上传和识别已完成，账单仍需你确认。" : "上传完成后，识别还会继续。重试沿用原任务。";
    }
  }
  function updateRow(item) {
    const state = item.controller?.state();
    item.remove.hidden = !!item.result || !!state && state.phase !== "editing";
    item.remove.disabled = sending || !state?.canRemove;
    item.retry.hidden = !!item.result || (!state?.onlineOnly && state?.phase === "editing");
    if (state?.onlineOnly) item.retry.textContent = "仅此张在线上传";
    item.retry.classList.toggle("product-button--primary", !!state?.onlineOnly);
    item.retry.classList.toggle("product-button--quiet", !state?.onlineOnly);
    if (item.result) item.form.querySelector("[data-attachment-status]").hidden = true;
  }
  async function preview(item, file) {
    const host = item.form.querySelector(".exp-thumb");
    try {
      const image = document.createElement("img");
      image.src = await window.TicketboxDraftFiles.imageSource(file);
      image.alt = "";
      await image.decode();
      host.replaceChildren(image);
    } catch (_) { host.textContent = "暂无法预览"; }
  }
  function removeRow(item) {
    items.splice(items.indexOf(item), 1);
    item.form.remove();
    update();
  }
  function accepted(item, result) {
    item.result = result;
    const message = item.form.querySelector("[data-capture-recognition]");
    message.hidden = false;
    message.dataset.inboxEnrichmentWatch = "";
    message.dataset.watchHref = result.next;
    message.dataset.watchInline = "";
    message.setAttribute("aria-busy", "true");
    message.querySelector("span").textContent = "图片已收到 · 识别任务已创建";
    const link = item.form.querySelector("[data-capture-open]");
    link.hidden = false;
    link.href = result.next;
    link.textContent = "查看进度";
    message.addEventListener("recognitioncomplete", event => {
      item.recognition = event.detail.state;
      link.textContent = event.detail.state === "updated" ? "去核对" : "查看原单";
      link.href = "/web/expenses/" + encodeURIComponent(result.receipt.id) + "/edit?ledger_id=" + encodeURIComponent(scope.ledgerId) + "&return_to=pending";
      update();
    });
    window.TicketboxWeb.initInboxEnrichmentWatch(item.form);
    update();
  }
  function add(file, record) {
    const ref = record?.clientRef || window.crypto.randomUUID().replaceAll("-", "");
    const action = new URL(record?.values.action || form.action);
    if (!record) {
      action.searchParams.set("idempotency_key", ref);
      action.searchParams.set("timezone", Intl.DateTimeFormat().resolvedOptions().timeZone || "");
    }
    const row = document.createElement("form");
    row.method = "post";
    row.enctype = "multipart/form-data";
    row.action = action.href;
    row.className = "product-entry product-entry--actions inbox-upload-task";
    row.dataset.inboxCapture = "";
    row.dataset.attachmentScope = form.dataset.attachmentScope;
    row.dataset.attachmentRef = ref;
    row.innerHTML = '<span class="exp-thumb"></span><div class="product-entry-copy"><strong></strong>' +
      '<p data-attachment-status role="status"></p><p data-capture-recognition hidden role="status"><span></span></p></div>' +
    '<div class="product-entry-actions"><button type="button" class="product-button product-button--quiet" data-capture-remove>移除</button>' +
      '<button type="submit" class="product-button product-button--quiet">重试原任务</button><a class="product-button product-button--quiet" data-capture-open hidden></a></div>' +
      '<input type="file" name="file" hidden><input type="hidden" name="csrf_token">';
    row.elements.namedItem("csrf_token").value = form.elements.namedItem("csrf_token").value;
    row.querySelector("strong").textContent = file?.name || record.values.file_name;
    if (file) {
      const transfer = new window.DataTransfer();
      transfer.items.add(file);
      row.elements.namedItem("file").files = transfer.files;
    }
    const item = {form: row, remove: row.querySelector("[data-capture-remove]"), retry: row.querySelector('[type="submit"]')};
    host.append(row);
    items.push(item);
    item.controller = entry.init(row, {batch: true, onChange: update,
      onReady: () => { if (file) void item.controller.capture(); }, onAccepted: result => accepted(item, result),
      onDiscarded: () => removeRow(item)});
    item.remove.addEventListener("click", async () => {
      try {
        if (!await item.controller.remove()) return;
        removeRow(item);
      } catch (_) { status.textContent = "图片未能移除，原文件和任务仍保留。"; }
    });
    if (file) preview(item, file);
    else window.TicketboxDraftFiles.get(drafts.store.key(ref), scope, record.values, drafts.store.matches)
      .then(saved => preview(item, saved)).catch(() => { row.querySelector(".exp-thumb").textContent = "原图待恢复"; });
    update();
  }
  picker.addEventListener("change", () => {
    for (const file of picker.files) add(file);
    picker.value = "";
    window.history.replaceState(null, "", "#capture");
    status.textContent = "选择后先保留原图；点击上传才会发送。";
  });
  stop.addEventListener("click", () => {
    stopped = true;
    stop.disabled = true;
    status.textContent = "正在结束当前一张；尚未发送的图片会保留，已收到的结果不会取消。";
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (sending) return;
    const ready = items.filter(item => !item.result && item.controller?.state().ready && !item.controller.state().onlineOnly);
    if (!ready.length) {
      if (items.some(item => item.result)) window.location.assign("/web/pending?ledger_id=" + encodeURIComponent(scope.ledgerId));
      return;
    }
    sending = true; stopped = false; attempted = true; stop.disabled = false; update();
    try {
      for (const item of ready) {
        if (stopped || !await item.controller.submit()) break;
      }
    } finally {
      sending = false;
      status.textContent = items.every(item => item.result) ? "图片已经安全收到，可从近期上传再次打开原单。" :
        "未完成的原图与任务仍保留；已收到的小票可在近期上传中找回。";
      update();
    }
  });
  try {
    drafts.store.list(scope).filter(record => new URL(record.values.action).pathname === "/web/pending/upload")
      .forEach(record => add(null, record));
    status.textContent = "选择图片，上传后仍需核对确认。";
    const wanted = /^#attachment-([a-f0-9]{32})$/.exec(window.location.hash);
    if (wanted && !items.some(item => item.form.dataset.attachmentRef === wanted[1])) {
      closedTask = true;
      status.textContent = drafts.store.read(wanted[1]) ? "原任务属于其他账本或身份；请恢复原身份后继续。" :
        "原任务已收起；请先核对账单，不会重新提交。";
    }
    entry.shelf(scope);
  } catch (_) {
    closedTask = /^#attachment-/.test(window.location.hash);
    status.textContent = "已有任务无法读取，请保留此页并检查浏览器存储。";
  }
  if (/^#(?:capture|attachment-[a-f0-9]{32})$/.test(window.location.hash)) form.closest("details").open = true;
  update();
  function nativePreview(nativeForm) {
    const task = nativeForm.closest("[data-inbox-upload]");
    const picker = nativeForm.elements.namedItem("file");
    const selection = task.querySelector("[data-capture-selection]");
    const host = task.querySelector("[data-capture-items]");
    const button = nativeForm.querySelector('[type="submit"]');
    button.setAttribute("form", nativeForm.id);
    task.querySelector("[data-capture-actions]").prepend(button);
    picker.addEventListener("change", () => {
      host.replaceChildren();
      const file = picker.files[0];
      selection.hidden = !file;
      if (!file) return;
      const row = document.createElement("div");
      row.className = "product-entry product-entry--actions inbox-upload-task";
      row.innerHTML = '<span class="exp-thumb"></span><span class="product-entry-copy"><strong></strong><span>准备上传</span></span>';
      void preview({form: row}, file);
      row.querySelector("strong").textContent = file.name;
      host.append(row);
      task.querySelector("[data-capture-count]").textContent = "1 张";
    });
  }
})(window, document);
