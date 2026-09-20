/* Explicit bounded observations; only a decoded snapshot can be user-verified. */
(function (window, document) {
  "use strict";
  const labels = {none: "没有关联原件", cleaned: "已按策略清理", missing: "文件缺失", corrupt: "内容不符",
    unverified: "尚未核验", verified: "原件一致", unreadable: "暂时无法读取"};
  const preview = document.querySelector("[data-original-preview]");
  let imageUrl;
  if (preview) preview.addEventListener("click", async () => {
    const status = document.querySelector("[data-original-preview-status]");
    const image = document.querySelector("[data-original-reviewed-image]");
    const check = document.querySelector("[data-original-reviewed]");
    if (check) { check.checked = false; check.disabled = true; }
    status.textContent = "正在读取实际原图…";
    try {
      const response = await window.fetch(preview.dataset.imageHref, {cache: "no-store", credentials: "same-origin"});
      if (!response.ok) throw Error("original_read_failed");
      const digest = /^"([a-f0-9]{64})"$/.exec(response.headers.get("etag") || "");
      if (!digest) throw Error("snapshot_digest_missing");
      const blob = await response.blob();
      if (imageUrl) window.URL.revokeObjectURL(imageUrl);
      imageUrl = window.URL.createObjectURL(blob);
      image.src = imageUrl;
      await image.decode();
      image.hidden = false;
      status.textContent = "实际原图已打开，请核对图片是否属于这笔账单。";
      if (check && check.form.dataset.attachmentPhase === "editing") {
        check.disabled = false;
        check.onchange = () => {
          const form = check.form;
          form.elements.namedItem("reviewed_sha256").value = check.checked ? digest[1] : "";
          form.querySelector('[type="submit"]').disabled = !check.checked;
          form.dispatchEvent(new Event("change", {bubbles: true}));
        };
      }
    } catch (_) { image.hidden = true; status.textContent = "实际原图未能打开，不能确认摘要。请稍后重试或补回原件。"; }
  });
  window.addEventListener("pagehide", () => { if (imageUrl) window.URL.revokeObjectURL(imageUrl); });
  const scan = document.querySelector("[data-original-scan]");
  if (scan) scan.addEventListener("click", async () => {
    scan.disabled = true;
    const status = document.querySelector("[data-original-scan-status]");
    const rows = [...document.querySelectorAll("[data-original-row]")].slice(0, 25);
    let finished = 0;
    for (const row of rows) {
      status.textContent = "正在检查 " + finished + " / " + rows.length;
      try {
        const response = await window.fetch(row.dataset.healthHref, {cache: "no-store", credentials: "same-origin"});
        if (!response.ok) throw Error("inspection_failed");
        const health = await response.json();
        row.querySelector("[data-original-row-status]").textContent = labels[health.state] + " · " + health.checked_at;
      } catch (_) { row.querySelector("[data-original-row-status]").textContent = "本次未能检查，可单独打开账单重试"; }
      finished += 1;
    }
    status.textContent = "本页检查结束 " + finished + " / " + rows.length + "；结果显示各自检查时间。";
    scan.disabled = false;
  });
})(window, document);
