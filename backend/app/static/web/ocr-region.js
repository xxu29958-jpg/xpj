/* A source-pixel selection is part of the existing durable recognition intent. */
(function (document) {
  "use strict";
  for (const panel of document.querySelectorAll("[data-ocr-region]")) {
    const form = panel.closest("form"), field = form.elements.namedItem("ocr_region");
    const image = panel.querySelector("[data-ocr-region-image]");
    const box = panel.querySelector("[data-ocr-region-box]"), status = panel.querySelector("[data-ocr-region-status]");
    let origin = null, selecting = true, zoom = 1;
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
      status.textContent = selected ? "已选一行。提交后仅重读选框内的文字。" : "未选择区域，将识别整张原件。";
    }
    function point(event) {
      const bounds = image.getBoundingClientRect();
      return [Math.round(Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * image.naturalWidth),
        Math.round(Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) * image.naturalHeight)];
    }
    function setSelection(selection) {
      field.value = selection ? JSON.stringify({image_sha256: panel.dataset.imageSha256, box: selection}) : "";
      field.dispatchEvent(new Event("input", {bubbles: true})); draw();
    }
    image.addEventListener("pointerdown", event => {
      if (!editable() || !selecting || !image.naturalWidth) return;
      event.preventDefault(); origin = point(event);
    });
    document.addEventListener("pointermove", event => {
      if (!origin || !editable()) return;
      const end = point(event);
      draw([Math.min(origin[0], end[0]), Math.min(origin[1], end[1]),
        Math.max(origin[0], end[0]), Math.max(origin[1], end[1])]);
    });
    document.addEventListener("pointerup", event => {
      if (!origin || !editable()) return;
      const end = point(event), selection = [Math.min(origin[0], end[0]), Math.min(origin[1], end[1]),
        Math.max(origin[0], end[0]), Math.max(origin[1], end[1])];
      origin = null;
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
    panel.querySelector("[data-ocr-region-move]").addEventListener("click", event => {
      if (!editable()) return;
      selecting = !selecting; origin = null;
      image.style.touchAction = selecting ? "none" : "pan-x pan-y pinch-zoom";
      event.currentTarget.textContent = selecting ? "移动图片" : "开始框选"; draw();
    });
    panel.querySelector("[data-ocr-region-clear]").addEventListener("click", () => { if (editable()) setSelection(null); });
    form.addEventListener("ocr-region-restored", () => draw());
    draw();
  }
})(document);
