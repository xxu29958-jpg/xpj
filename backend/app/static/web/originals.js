/* Explicit bounded observations; only a decoded snapshot can be user-verified. */
(function (window, document) {
  "use strict";
  const labels = {none: "没有关联原件", cleaned: "已按策略清理", missing: "文件缺失", corrupt: "内容不符",
    unverified: "尚未核验", verified: "原件一致", unreadable: "暂时无法读取"};
  const preview = document.querySelector("[data-original-preview]");
  const check = document.querySelector("[data-original-reviewed]");
  let decodedDigest = null;
  function reviewAvailability() {
    if (!check || check.form.dataset.attachmentPhase !== "editing") return;
    check.disabled = !decodedDigest;
    check.onchange = () => {
      const form = check.form;
      form.elements.namedItem("reviewed_sha256").value = check.checked ? decodedDigest : "";
      form.querySelector('[type="submit"]').disabled = !check.checked;
      form.dispatchEvent(new Event("change", {bubbles: true}));
    };
  }
  check?.form.addEventListener("attachment-ready", reviewAvailability);
  if (preview) preview.addEventListener("click", async () => {
    const status = document.querySelector("[data-original-preview-status]");
    const image = document.querySelector("[data-original-reviewed-image]");
    const controls = document.querySelector("[data-original-controls]");
    preview.disabled = true;
    decodedDigest = null;
    image.hidden = true;
    controls.hidden = true;
    status.classList.remove("sr-only");
    if (check && check.form.dataset.attachmentPhase === "editing") {
      const hadReview = !!check.form.elements.namedItem("reviewed_sha256").value;
      check.checked = false; check.disabled = true;
      check.form.elements.namedItem("reviewed_sha256").value = "";
      check.form.querySelector('[type="submit"]').disabled = true;
      if (hadReview) check.form.dispatchEvent(new Event("change", {bubbles: true}));
    }
    status.textContent = "正在读取实际原图…";
    try {
      const response = await window.fetch(preview.dataset.imageHref, {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw Error("original_read_failed");
      const digest = /^"([a-f0-9]{64})"$/.exec(response.headers.get("etag") || "");
      if (!digest) throw Error("snapshot_digest_missing");
      const blob = await response.blob();
      image.src = await new Promise((resolve, reject) => {
        const reader = new window.FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      });
      await image.decode();
      image.hidden = false;
      controls.hidden = false;
      window.TicketboxWeb.bindReceiptControls(document, image);
      status.classList.add("sr-only");
      status.textContent = "实际原图已打开，请核对图片是否属于这笔账单。";
      decodedDigest = digest[1];
      reviewAvailability();
    } catch (_) { image.hidden = true; status.textContent = "实际原图未能打开，不能确认摘要。请稍后重试或补回原件。"; }
    finally { preview.disabled = false; preview.textContent = image.hidden ? "重试读取原图" : "重新读取原图"; }
  });
  if (preview) preview.click();
  const states = {
    verified: {action: "可查看", tone: "success", priority: 3},
    none: {action: "无需处理", tone: "success", priority: 3},
    cleaned: {action: "已清理", tone: "info", priority: 3},
    missing: {action: "补回", tone: "warning", priority: 0},
    corrupt: {action: "核对并补回", tone: "warning", priority: 0},
    unverified: {action: "核验", tone: "warning", priority: 1},
    unreadable: {action: "重试", tone: "warning", priority: 2},
  };
  function showInspection(row, health) {
    const state = states[health.state];
    row.dataset.originalState = health.state;
    row.querySelector("[data-original-row-status]").textContent = labels[health.state];
    const action = row.querySelector("[data-original-row-action]");
    action.textContent = state.action;
    action.className = "product-status product-status--" + state.tone;
    row.querySelector("[data-original-row-time]").textContent = health.checked_at ?
      "检查于 " + new Date(health.checked_at).toLocaleString("zh-CN", {hour12: false}) : "本次未能检查，可打开账单重试";
    row.querySelector(".product-entry-icon").classList.toggle("product-entry-icon--apricot", state.priority < 3);
  }
  const scan = document.querySelector("[data-original-scan]");
  let inspected = false;
  if (scan) scan.addEventListener("click", async () => {
    inspected = true;
    scan.disabled = true;
    document.querySelector("[data-original-next]").hidden = true;
    const status = document.querySelector("[data-original-scan-status]");
    const rows = [...document.querySelectorAll("[data-original-row]")].slice(0, 25);
    let finished = 0;
    for (const row of rows) {
      status.textContent = "正在检查 " + finished + " / " + rows.length;
      try {
        const response = await window.fetch(row.dataset.healthHref, {cache: "no-store", credentials: "same-origin"});
        if (!response.ok) throw Error("inspection_failed");
        const health = await response.json();
        if (!states[health.state] || String(health.expense_id) !== row.dataset.expenseId) throw Error("inspection_failed");
        showInspection(row, health);
      } catch (_) { showInspection(row, {state: "unreadable"}); }
      finished += 1;
    }
    status.textContent = "本页检查结束 " + finished + " / " + rows.length + "；结果显示各自检查时间。";
    rows.sort((a, b) => states[a.dataset.originalState].priority - states[b.dataset.originalState].priority);
    document.querySelector("[data-original-list]").append(...rows);
    const missing = rows.filter(row => states[row.dataset.originalState].priority === 0);
    const attention = rows.filter(row => states[row.dataset.originalState].priority < 3);
    document.querySelector("[data-original-scan-heading]").textContent = missing.length ?
      "有 " + missing.length + " 张原件需要补回" : attention.length ? "有 " + attention.length + " 笔需要核对" : "本页原件检查完成";
    const next = document.querySelector("[data-original-next]");
    next.hidden = !attention.length;
    if (attention.length) { next.href = attention[0].href; next.textContent = missing.length ? "补回缺失原件" : "查看需要核对的原件"; }
    scan.classList.toggle("product-button--primary", !attention.length);
    scan.classList.toggle("product-button--quiet", !!attention.length);
    scan.textContent = "重新检查本页";
    scan.disabled = false;
  });
  if (document.querySelector("[data-original-resume]")) scan?.click();
  window.addEventListener("pageshow", event => { if (event.persisted && inspected) scan?.click(); });
})(window, document);
