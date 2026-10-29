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
      '<details data-feedback-lines hidden><summary>从已识别文字中选位置</summary><p>点选文字行可指出范围，仍需对照原图核对。</p><div data-feedback-line-list></div></details>' +
      '<div class="product-form-actions"><button type="button" data-source-close>返回填写</button>' +
      '<button type="button" data-source-previous>上一处</button><button type="button" data-source-next>下一处</button>' +
      '<button type="button" data-source-zoom="0.5">缩小</button><button type="button" data-source-zoom="2">放大</button>' +
      '<button type="button" data-feedback-mode="browse" hidden>浏览原图</button><button type="button" data-feedback-mode="corners" hidden>指出位置 / 两点调整范围</button>' +
      '<button type="button" data-feedback-clear hidden>不定位</button><button type="button" data-feedback-use hidden>使用这一位置</button></div>';
    dialog.querySelectorAll("button").forEach(button => { button.className = "product-button product-button--quiet"; });
    form.append(dialog);
    dialog.addEventListener("keydown", event => {
      if (event.key === "Escape" || event.key === "Tab") event.stopPropagation();
    });
    const viewer = {dialog, form, image: dialog.querySelector("img"), svg: dialog.querySelector("svg"),
      surface: dialog.querySelector(".recognition-source-surface"), scroll: dialog.querySelector(".recognition-source-scroll"),
      status: dialog.querySelector("[data-source-status]"), zoom: 1, digest: null, selected: null, revision: 0};
    dialog.querySelector("[data-source-close]").onclick = () => dialog.close();
    installFeedbackSelection(viewer);
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
  function viewerFor(form) {
    if (!viewers.has(form)) viewers.set(form, createViewer(form));
    return viewers.get(form);
  }
  async function loadOriginal(viewer, href, digest, revision) {
    if (viewer.digest !== digest) {
      viewer.surface.hidden = true;
      const response = await fetch(href, {credentials: "same-origin", cache: "no-store"});
      if (!response.ok || !/^[a-f0-9]{64}$/.test(digest) || response.headers.get("etag") !== '"' + digest + '"') throw Error("source_changed");
      const blob = await response.blob();
      const source = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error); reader.readAsDataURL(blob);
      });
      if (revision !== viewer.revision) throw Error("source_changed");
      viewer.image.src = source;
      await viewer.image.decode();
      if (revision !== viewer.revision) throw Error("source_changed");
      viewer.digest = digest;
    }
    return {image_sha256: digest, width: viewer.image.naturalWidth, height: viewer.image.naturalHeight,
      coordinate_space: "exif-transposed-pixels"};
  }
  function feedbackMode(viewer, enabled) {
    viewer.feedback = enabled; viewer.mode = "browse"; viewer.image.style.touchAction = "pan-x pan-y pinch-zoom";
    viewer.dialog.querySelectorAll("[data-feedback-mode], [data-feedback-clear], [data-feedback-use]").forEach(item => { item.hidden = !enabled; });
    viewer.dialog.querySelectorAll("[data-source-previous], [data-source-next]").forEach(item => { item.hidden = enabled; });
    viewer.dialog.querySelector("[data-feedback-lines]").hidden = true;
    viewer.dialog.querySelectorAll("[data-feedback-mode]").forEach(item => { item.setAttribute("aria-pressed", String(item.dataset.feedbackMode === "browse")); });
  }
  function drawFeedback(viewer) {
    viewer.svg.replaceChildren();
    const value = viewer.annotation;
    let shape;
    if (value.box) {
      const [x1, y1, x2, y2] = value.box;
      shape = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      shape.setAttribute("points", `${x1},${y1} ${x2},${y1} ${x2},${y2} ${x1},${y2}`);
    } else if (value.point) {
      shape = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      shape.setAttribute("cx", value.point[0]); shape.setAttribute("cy", value.point[1]); shape.setAttribute("r", "5");
    }
    if (shape) viewer.svg.append(shape);
    viewer.status.textContent = value.box ? "范围尚待你核对。返回后可确认它与原文对应。"
      : value.point ? "已记录大致位置。可以直接使用，也可再点另一角划出范围。" : "可以只浏览。位置可跳过；点一下记录大致位置，两点调整范围。";
  }
  function showTextLines(viewer) {
    const source = JSON.parse(viewer.form.querySelector("[data-recognition-text-lines]")?.textContent || "null");
    const group = viewer.dialog.querySelector("[data-feedback-lines]"), list = group.querySelector("[data-feedback-line-list]");
    list.replaceChildren(); group.open = false;
    if (!source || source.image_sha256 !== viewer.digest || source.width !== viewer.image.naturalWidth ||
        source.height !== viewer.image.naturalHeight || source.coordinate_space !== "exif-transposed-pixels") return;
    group.hidden = source.lines.length === 0;
    source.lines.forEach(line => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "recognition-candidate"; button.dataset.feedbackLine = "";
      button.textContent = line.text;
      button.onclick = () => {
        viewer.annotation = {...viewer.annotation, box: [...line.box], point: null, location_state: "suggested_region"};
        drawFeedback(viewer);
        resize(viewer, viewer.zoom, [(line.box[0] + line.box[2]) / 2, (line.box[1] + line.box[3]) / 2]);
      };
      list.append(button);
    });
  }
  function installFeedbackSelection(viewer) {
    let origin = null;
    viewer.image.addEventListener("pointerdown", event => {
      origin = viewer.feedback && viewer.mode === "corners" && event.isPrimary && event.button === 0 ? [event.clientX, event.clientY] : null;
    });
    viewer.image.addEventListener("pointercancel", () => { origin = null; });
    viewer.image.addEventListener("pointerup", event => {
      const start = origin; origin = null;
      if (!start || Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 8) return;
      const bounds = viewer.image.getBoundingClientRect();
      const point = [Math.round(Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * viewer.image.naturalWidth),
        Math.round(Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) * viewer.image.naturalHeight)];
      const first = viewer.annotation.point;
      const box = first && [Math.min(first[0], point[0]), Math.min(first[1], point[1]), Math.max(first[0], point[0]), Math.max(first[1], point[1])];
      if (box && box[2] - box[0] >= 4 && box[3] - box[1] >= 4) viewer.annotation = {...viewer.annotation, box, point: null, location_state: "suggested_region"};
      else viewer.annotation = {...viewer.annotation, box: null, point, location_state: "coarse_point"};
      drawFeedback(viewer);
    });
    viewer.dialog.querySelectorAll("[data-feedback-mode]").forEach(button => { button.onclick = () => {
      viewer.mode = button.dataset.feedbackMode;
      viewer.image.style.touchAction = viewer.mode === "browse" ? "pan-x pan-y pinch-zoom" : "pinch-zoom";
      viewer.dialog.querySelectorAll("[data-feedback-mode]").forEach(item => { item.setAttribute("aria-pressed", String(item === button)); });
    }; });
    viewer.dialog.querySelector("[data-feedback-clear]").onclick = () => {
      viewer.annotation = {...viewer.annotation, point: null, box: null, location_state: "unlocated"}; drawFeedback(viewer);
    };
    viewer.dialog.querySelector("[data-feedback-use]").onclick = () => { viewer.apply(viewer.annotation); viewer.dialog.close(); };
  }
  window.TicketboxRecognitionSource = {
    original(form, href, digest) {
      const viewer = viewerFor(form);
      return loadOriginal(viewer, href, digest, ++viewer.revision);
    },
    async locate(form, href, annotation, apply) {
      const viewer = viewerFor(form), revision = ++viewer.revision;
      feedbackMode(viewer, true); viewer.apply = apply; viewer.annotation = {...annotation}; viewer.selected = null;
      viewer.dialog.querySelector("[data-source-title]").textContent = "对照原图文字";
      viewer.dialog.querySelector("[data-source-text]").textContent = annotation.verbatim_text;
      viewer.status.textContent = "正在对照原图…"; viewer.surface.hidden = true;
      viewer.dialog.querySelector("[data-feedback-use]").disabled = true;
      viewer.dialog.showModal();
      try {
        const source = await loadOriginal(viewer, href, annotation.image_sha256, revision);
        if (revision !== viewer.revision) return;
        viewer.annotation = {...viewer.annotation, ...source};
        viewer.svg.setAttribute("viewBox", `0 0 ${source.width} ${source.height}`);
        viewer.surface.hidden = false; resize(viewer, 1, [source.width / 2, source.height / 2]);
        viewer.dialog.querySelectorAll("[data-source-zoom], [data-feedback-use]").forEach(item => { item.disabled = false; });
        drawFeedback(viewer);
        showTextLines(viewer);
      } catch (_) { if (revision === viewer.revision) viewer.status.textContent = "原图暂时无法核对。返回后仍保留填写；可稍后重试或移除此反馈。"; }
    }
  };
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
    feedbackMode(viewer, false);
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
      await loadOriginal(viewer, button.dataset.sourceImageHref, location.image_sha256, revision);
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
    show(viewerFor(form), button);
  });
})();
