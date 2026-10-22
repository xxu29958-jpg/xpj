/* Observe completion without replacing a user's open draft or OCC basis. */
(function (window, document) {
  "use strict";
  const marker = document.querySelector("[data-expense-ocr-watch]");
  if (!marker || marker.dataset.ocrActive !== "true") return;
  const messages = JSON.parse(marker.dataset.ocrMessages);
  const deadline = Date.now() + 120000;
  const message = marker.querySelector("[data-ocr-task-message]");
  function stop(text) {
    marker.setAttribute("aria-busy", "false");
    message.textContent = text;
  }
  async function poll() {
    if (!marker.isConnected) return;
    if (Date.now() >= deadline) {
      stop("识别还未返回结果，可以继续填写或稍后重新打开账单查看。");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(marker.dataset.ocrStatusHref, {
        cache: "no-store", credentials: "same-origin", headers: {Accept: "application/json"}, signal: controller.signal,
      });
      if ([401, 403, 404].includes(response.status)) {
        stop("当前无法读取这次识别状态，填写仍保留；请核对登录身份和账本。");
        marker.querySelector("[data-ocr-cancel]")?.setAttribute("hidden", "");
        return;
      }
      if (response.ok) {
        const task = await response.json();
        if (task.public_id !== marker.dataset.ocrTaskId || task.source_expense_id !== Number(marker.dataset.ocrExpenseId)) return;
        if (!["queued", "running"].includes(task.status)) {
          const state = task.status === "completed" ? task.result_summary?.outcome : task.status;
          stop(messages[state] || messages.failed);
          marker.querySelector("[data-ocr-cancel]")?.setAttribute("hidden", "");
          marker.querySelector("[data-ocr-result-link]").hidden = false;
          return;
        }
        message.textContent = messages[task.status];
      }
    } catch (error) {
      // The bounded observer may retry a failed read; it never resubmits OCR.
      message.textContent = "识别状态暂未更新，可以继续填写。";
    } finally {
      window.clearTimeout(timer);
    }
    window.setTimeout(poll, 1500);
  }
  window.setTimeout(poll, 1500);
})(window, document);
