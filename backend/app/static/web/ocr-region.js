/* A source-pixel selection is part of the existing durable recognition intent. */
(function (document) {
  "use strict";
  for (const panel of document.querySelectorAll("[data-ocr-region]")) {
    const form = panel.closest("form"), field = form.elements.namedItem("ocr_region");
    const image = panel.querySelector("[data-ocr-region-image]");
    const box = panel.querySelector("[data-ocr-region-box]"), status = panel.querySelector("[data-ocr-region-status]");
    let origin = null, corner = null, mode = "browse", zoom = 1;
    const surface = panel.querySelector("[data-ocr-region-surface]");
    const editable = () => form.dataset.ocrRegionEditable === "true";
    function draw(selected = field.value ? JSON.parse(field.value).box : null) {
      box.hidden = !selected;
      if (selected && image.naturalWidth) {
        box.style.left = 100 * selected[0] / image.naturalWidth + "%";
        box.style.top = 100 * selected[1] / image.naturalHeight + "%";
        box.style.width = 100 * (selected[2] - selected[0]) / image.naturalWidth + "%";
        box.style.height = 100 * (selected[3] - selected[1]) / image.naturalHeight + "%";
      }
      status.textContent = corner ? "已选第一个角，再点这一行的另一个对角。可先放大或移动图片。"
        : selected ? "已选一行。提交后仅重读选框内的文字。" : "未选择区域，将识别整张原件。";
    }
    function point(event) {
      const bounds = image.getBoundingClientRect();
      return [Math.round(Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * image.naturalWidth),
        Math.round(Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) * image.naturalHeight)];
    }
    function setSelection(selection) {
      corner = null;
      field.value = selection ? JSON.stringify({image_sha256: panel.dataset.imageSha256, box: selection}) : "";
      field.dispatchEvent(new Event("input", {bubbles: true})); draw();
    }
    function rectangle(start, end) {
      return [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
        Math.max(start[0], end[0]), Math.max(start[1], end[1])];
    }
    image.addEventListener("pointerdown", event => {
      if (!event.isPrimary) { origin = null; draw(); return; }
      if (!editable() || mode === "browse" || !image.naturalWidth || event.button !== 0) return;
      event.preventDefault();
      origin = {point: point(event), client: [event.clientX, event.clientY], id: event.pointerId};
    });
    document.addEventListener("pointermove", event => {
      if (!origin || !editable() || event.pointerId !== origin.id) return;
      if (mode === "drag") draw(rectangle(origin.point, point(event)));
      else if (Math.hypot(event.clientX - origin.client[0], event.clientY - origin.client[1]) > 8) origin = null;
    });
    document.addEventListener("pointerup", event => {
      if (!origin || !editable() || event.pointerId !== origin.id) return;
      const end = point(event), start = origin.point;
      origin = null;
      if (mode === "corners" && !corner) { corner = end; draw(rectangle(end, end)); return; }
      const selection = rectangle(mode === "corners" ? corner : start, end);
      if (selection[2] - selection[0] < 4 || selection[3] - selection[1] < 4) return;
      setSelection(selection);
    });
    document.addEventListener("pointercancel", () => { origin = null; draw(); });
    image.addEventListener("load", () => draw());
    for (const button of panel.querySelectorAll("[data-ocr-region-zoom]")) button.addEventListener("click", () => {
      if (!editable()) return;
      zoom = Math.min(16, Math.max(1, zoom * Number(button.dataset.ocrRegionZoom)));
      surface.style.width = zoom * 100 + "%"; draw();
    });
    for (const button of panel.querySelectorAll("[data-ocr-region-mode]")) button.addEventListener("click", () => {
      if (!editable()) return;
      mode = button.dataset.ocrRegionMode; origin = null;
      image.style.touchAction = mode === "browse" ? "pan-x pan-y pinch-zoom" : mode === "corners" ? "pinch-zoom" : "none";
      for (const item of panel.querySelectorAll("[data-ocr-region-mode]")) item.setAttribute("aria-pressed", String(item === button));
      draw();
    });
    panel.querySelector("[data-ocr-region-clear]").addEventListener("click", () => { if (editable()) setSelection(null); });
    form.addEventListener("ocr-region-restored", () => draw());
    draw();
  }
})(document);
