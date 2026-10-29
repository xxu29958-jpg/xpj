/* Optional original review: source blocks never mutate a financial or feedback intent. */
(function () {
  "use strict";
  const viewers = new WeakMap();
  function createViewer(form) {
    const dialog = document.createElement("dialog");
    dialog.className = "recognition-source-dialog";
    dialog.setAttribute("aria-label", "对照原图来源");
    dialog.innerHTML = '<strong data-source-title></strong><p data-source-text></p>' +
      '<p role="status" data-source-status></p><div class="recognition-source-scroll"><div class="recognition-source-surface">' +
      '<img alt="候选对应的实际原图" draggable="false"><svg aria-hidden="true"></svg></div></div>' +
      '<div class="product-form-actions"><button type="button" data-source-close>返回填写</button>' +
      '<button type="button" data-source-previous>上一处</button><button type="button" data-source-next>下一处</button>' +
      '<button type="button" data-source-zoom="0.5">缩小</button><button type="button" data-source-zoom="2">放大</button></div>';
    dialog.querySelectorAll("button").forEach(button => { button.className = "product-button product-button--quiet"; });
    form.append(dialog);
    dialog.addEventListener("keydown", event => {
      const confirm = event.key === "Enter" && (event.ctrlKey || event.metaKey);
      if (confirm) event.preventDefault();
      if (confirm || event.key === "Escape" || event.key === "Tab") event.stopPropagation();
    });
    const viewer = {dialog, form, image: dialog.querySelector("img"), svg: dialog.querySelector("svg"),
      surface: dialog.querySelector(".recognition-source-surface"), scroll: dialog.querySelector(".recognition-source-scroll"),
      status: dialog.querySelector("[data-source-status]"), zoom: 1, digest: null, selected: null, revision: 0};
    dialog.querySelector("[data-source-close]").onclick = () => dialog.close();
    for (const [name, delta] of [["previous", -1], ["next", 1]]) {
      dialog.querySelector(`[data-source-${name}]`).onclick = () => show(viewer, viewer.buttons[viewer.index + delta]);
    }
    dialog.querySelectorAll("[data-source-zoom]").forEach(button => { button.onclick = () => {
      const oldScale = viewer.surface.clientWidth / viewer.image.naturalWidth;
      const center = [(viewer.scroll.scrollLeft + viewer.scroll.clientWidth / 2) / oldScale,
        (viewer.scroll.scrollTop + viewer.scroll.clientHeight / 2) / oldScale];
      resize(viewer, viewer.zoom * Number(button.dataset.sourceZoom), center);
    }; });
    return viewer;
  }
  function resize(viewer, zoom, center) {
    viewer.zoom = Math.max(1, Math.min(16, zoom));
    const width = viewer.scroll.clientWidth * viewer.zoom;
    viewer.surface.style.width = width + "px";
    const scale = width / viewer.image.naturalWidth;
    viewer.scroll.scrollLeft = center[0] * scale - viewer.scroll.clientWidth / 2;
    viewer.scroll.scrollTop = center[1] * scale - viewer.scroll.clientHeight / 2;
  }
  async function show(viewer, button) {
    const revision = ++viewer.revision, candidate = JSON.parse(button.dataset.recognitionSource), location = candidate.source_location;
    viewer.buttons = [...viewer.form.querySelectorAll("[data-recognition-source]")];
    viewer.index = viewer.buttons.indexOf(button);
    viewer.dialog.querySelector("[data-source-previous]").disabled = viewer.index === 0;
    viewer.dialog.querySelector("[data-source-next]").disabled = viewer.index === viewer.buttons.length - 1;
    viewer.dialog.querySelector("[data-source-title]").textContent = candidate.label;
    viewer.dialog.querySelector("[data-source-text]").textContent = candidate.original_text;
    if (!viewer.dialog.open) viewer.dialog.showModal();
    viewer.status.textContent = "正在对照原图…";
    viewer.dialog.querySelectorAll("[data-source-zoom]").forEach(control => { control.disabled = true; });
    viewer.svg.replaceChildren();
    try {
      if (viewer.digest !== location.image_sha256) {
        viewer.surface.hidden = true;
        const response = await fetch(button.dataset.sourceImageHref, {credentials: "same-origin", cache: "no-store"});
        if (!response.ok || response.headers.get("etag") !== '"' + location.image_sha256 + '"') throw Error("source_changed");
        const blob = await response.blob();
        const source = await new Promise((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(reader.error); reader.readAsDataURL(blob);
        });
        if (revision !== viewer.revision) return;
        viewer.image.src = source;
        await viewer.image.decode();
        if (revision !== viewer.revision) return;
        viewer.digest = location.image_sha256;
      }
      if (revision !== viewer.revision) return;
      if (viewer.image.naturalWidth !== location.width || viewer.image.naturalHeight !== location.height ||
          location.coordinate_space !== "exif-transposed-pixels") throw Error("geometry_changed");
      viewer.surface.hidden = false;
      viewer.dialog.querySelectorAll("[data-source-zoom]").forEach(control => { control.disabled = false; });
      viewer.svg.setAttribute("viewBox", `0 0 ${location.width} ${location.height}`);
      for (const box of location.boxes) {
        const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        polygon.setAttribute("points", box.map(point => point.join(",")).join(" ")); viewer.svg.append(polygon);
      }
      if (viewer.selected !== candidate.id) {
        const points = location.boxes.flat(), xs = points.map(point => point[0]), ys = points.map(point => point[1]);
        const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
        const zoom = Math.min(viewer.scroll.clientWidth / Math.max(1, right - left),
          viewer.scroll.clientHeight / Math.max(1, bottom - top)) * .8 * location.width / viewer.scroll.clientWidth;
        resize(viewer, zoom, [(left + right) / 2, (top + bottom) / 2]);
      }
      viewer.selected = candidate.id;
      viewer.status.textContent = "高亮来自这一候选的识别文字框。可继续浏览；返回保留当前填写。";
    } catch (_) {
      if (revision !== viewer.revision) return;
      viewer.surface.hidden = true; viewer.digest = null;
      viewer.status.textContent = "无法核对原图与这次识别的位置。仍可返回填写，或重新打开原件。";
    }
  }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-recognition-source]");
    if (!button) return;
    const form = button.closest("form");
    if (!form) return;
    if (!viewers.has(form)) viewers.set(form, createViewer(form));
    show(viewers.get(form), button);
  });
})();
