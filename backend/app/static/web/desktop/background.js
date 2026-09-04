/* 自定义背景 control（全局背景批）— 外观 popover 第四轴「背景」。
 *
 * 存储 / 渲染 owner 是 appearance-bootstrap.js 的 TicketboxBackground（内页与
 * auth/login 同一管线）；本模块只做三件事：导入图片（canvas 降采样 + 诚实
 * 编码）、编辑面（拖动 / 缩放 / 微调构图的实时预览）、应用 / 取消 / 恢复默认。
 *
 * 语义红线：
 * - 预览只改 <html> 上的 var（真实管线实时上屏），草稿绝不先发布成 current；
 * - 应用 = TicketboxBackground.apply 单一 IDB record 单事务提交，成功才转正，
 *   commit 失败保留草稿与编辑面，不伪成功；
 * - 取消 = restoreApplied 还原到已应用的图 / transform，无副作用。
 *
 * 诚实编码：仅 image/jpeg 源走 JPEG(q0.85) 重编码；PNG/WEBP/GIF 等可能含
 * 透明的格式一律 PNG 导出，绝不把透明拍成黑底；长边降采样 ≤2048。
 */
(function (window, document) {
  "use strict";

  var app = window.TicketboxWeb = window.TicketboxWeb || {};

  var MAX_IMAGE_SIDE = 2048;
  var RETRY_IMAGE_SIDE = 1024;
  var MAX_DATAURL_LENGTH = 4 * 1024 * 1024;

  var MSG_IMPORT_FAILED = "图片读取失败，请换一张再试。";
  var MSG_TOO_LARGE = "图片太大，压缩后仍超出本地保存上限，请换一张再试。";
  var MSG_SAVE_FAILED = "背景没有保存成功，请重试。";
  var MSG_CLEAR_FAILED = "没有恢复成默认背景，请重试。";

  app.initBackgroundControl = function initBackgroundControl() {
    var bg = window.TicketboxBackground;
    // bootstrap 未加载（静态资产失败）时背景轴整体不可用，诚实静默退出。
    if (!bg) return;
    var roots = document.querySelectorAll("[data-appearance-popover]");
    if (!roots.length) return;

    var constants = bg.constants;
    var draft = null;
    var editorOpen = false;
    var busy = false;

    /* ── 导入：文件 → dataURL → Image 解码 → canvas 降采样 → 诚实编码 ── */

    var fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.hidden = true;
    document.body.appendChild(fileInput);

    function readFile(file) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onload = function () { resolve(String(reader.result || "")); };
        reader.onerror = function () { reject(new Error("read failed")); };
        reader.readAsDataURL(file);
      });
    }

    function decodeImage(dataUrl) {
      return new Promise(function (resolve, reject) {
        var img = new Image();
        img.onload = function () { resolve(img); };
        img.onerror = function () { reject(new Error("decode failed")); };
        img.src = dataUrl;
      });
    }

    function encodeImage(img, isJpeg, maxSide) {
      var w = img.naturalWidth || 0;
      var h = img.naturalHeight || 0;
      if (!w || !h) throw new Error("empty image");
      var ratio = Math.min(1, maxSide / Math.max(w, h));
      var cw = Math.max(1, Math.round(w * ratio));
      var ch = Math.max(1, Math.round(h * ratio));
      var canvas = document.createElement("canvas");
      canvas.width = cw;
      canvas.height = ch;
      var ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("canvas unavailable");
      ctx.drawImage(img, 0, 0, cw, ch);
      // JPEG 不带透明通道；其余格式一律 PNG，透明如实保留。
      var dataUrl = isJpeg
        ? canvas.toDataURL("image/jpeg", 0.85)
        : canvas.toDataURL("image/png");
      if (!dataUrl || dataUrl.indexOf("data:") !== 0) throw new Error("encode failed");
      return { image: dataUrl, width: cw, height: ch };
    }

    function processFile(file) {
      var isJpeg = file.type === "image/jpeg";
      return readFile(file)
        .then(decodeImage)
        .then(function (img) {
          var encoded = encodeImage(img, isJpeg, MAX_IMAGE_SIDE);
          if (encoded.image.length > MAX_DATAURL_LENGTH) {
            encoded = encodeImage(img, isJpeg, RETRY_IMAGE_SIDE);
          }
          if (encoded.image.length > MAX_DATAURL_LENGTH) {
            var error = new Error("image too large");
            error.tooLarge = true;
            throw error;
          }
          return {
            image: encoded.image,
            width: encoded.width,
            height: encoded.height,
            // 新图构图重置；重新编辑已应用图时保留 transform（见 openEditor）。
            transform: { scale: 1, offsetX: 0, offsetY: 0 }
          };
        });
    }

    /* ── 编辑面：原生 <dialog> + showModal（与 confirm-modal 同一项目机制）──
     * 焦点隔离 / Esc / 关闭后焦点回触发器全部走原生 top-layer 语义；
     * 全屏拖动层 + 底部控制条，直改 root var 实时预览。 */

    var editor = document.createElement("dialog");
    editor.className = "bg-editor";
    editor.innerHTML =
      '<div class="bg-editor-stage" data-bg-stage></div>' +
      '<div class="bg-editor-bar" role="group" aria-label="调整背景">' +
      '<p class="bg-editor-hint">拖动画面调整构图，应用后对所有页面生效，图片只保存在本机。</p>' +
      '<p class="bg-editor-status" data-bg-status aria-live="polite" hidden></p>' +
      '<div class="bg-editor-controls">' +
      '<button type="button" data-bg-act="zoom-out">缩小</button>' +
      '<button type="button" data-bg-act="reset">重置构图</button>' +
      '<button type="button" data-bg-act="zoom-in">放大</button>' +
      '<span class="bg-editor-nudge">' +
      '<button type="button" data-bg-act="left" aria-label="左移">←</button>' +
      '<button type="button" data-bg-act="up" aria-label="上移">↑</button>' +
      '<button type="button" data-bg-act="down" aria-label="下移">↓</button>' +
      '<button type="button" data-bg-act="right" aria-label="右移">→</button>' +
      '</span>' +
      '<span class="bg-editor-actions">' +
      '<button type="button" data-bg-act="cancel">取消</button>' +
      '<button type="button" class="bg-editor-apply" data-bg-act="apply">应用背景</button>' +
      '</span>' +
      '</div>' +
      '</div>';
    document.body.appendChild(editor);

    var stage = editor.querySelector("[data-bg-stage]");
    var status = editor.querySelector("[data-bg-status]");
    var applyButton = editor.querySelector('[data-bg-act="apply"]');

    function setStatus(message) {
      if (!message) {
        status.hidden = true;
        status.textContent = "";
      } else {
        status.hidden = false;
        status.textContent = message;
      }
    }

    function setBusy(next) {
      busy = next;
      editor.querySelectorAll("button").forEach(function (button) {
        button.disabled = next;
      });
      applyButton.textContent = next ? "应用中…" : "应用背景";
    }

    function updateDraft(next) {
      if (!editorOpen || busy || !next) return;
      draft = next;
      bg.preview(draft);
    }

    function openEditor(nextDraft) {
      draft = nextDraft;
      editorOpen = true;
      setStatus("");
      setBusy(false);
      bg.preview(draft);
      // 原生 top-layer:焦点进入编辑面,Tab 不再掉到下层表单;关闭时
      // 浏览器管理关闭后的焦点（原入口已隐藏时可能回到 BODY）。旧浏览器无 showModal 时退化为
      // 普通 open 面板(功能可用,焦点隔离降级,诚实可接受)。
      if (typeof editor.showModal === "function") {
        editor.showModal();
      } else {
        editor.setAttribute("open", "");
      }
      applyButton.focus();
    }

    function closeEditor() {
      editorOpen = false;
      draft = null;
      if (editor.open) {
        editor.close();
      } else {
        editor.removeAttribute("open");
      }
    }

    function cancelEditor() {
      if (busy) return;
      // 取消 = 还原已应用的图 / transform；预览期间的 var 改动全部回退。
      bg.restoreApplied();
      closeEditor();
    }

    function applyEditor() {
      if (busy || !draft) return;
      setBusy(true);
      bg.apply(draft).then(function () {
        closeEditor();
        syncButtons();
      }).catch(function () {
        // commit 失败：草稿留在编辑面，不成为 current，不伪成功。
        setBusy(false);
        setStatus(MSG_SAVE_FAILED);
      });
    }

    /* 手势：拖动平移（指针捕获，触屏 mouse 同一路径）。 */
    var dragLast = null;
    stage.addEventListener("pointerdown", function (event) {
      if (!editorOpen || busy) return;
      dragLast = { x: event.clientX, y: event.clientY };
      stage.setPointerCapture(event.pointerId);
    });
    stage.addEventListener("pointermove", function (event) {
      if (!dragLast || !editorOpen || busy) return;
      var dx = event.clientX - dragLast.x;
      var dy = event.clientY - dragLast.y;
      dragLast = { x: event.clientX, y: event.clientY };
      updateDraft(bg.panBy(draft, dx, dy));
    });
    stage.addEventListener("pointerup", function () { dragLast = null; });
    stage.addEventListener("pointercancel", function () { dragLast = null; });

    /* 滚轮缩放（编辑面打开时接管，避免页面滚动干扰构图）。 */
    stage.addEventListener("wheel", function (event) {
      if (!editorOpen || busy) return;
      event.preventDefault();
      var factor = event.deltaY < 0 ? constants.ZOOM_STEP : 1 / constants.ZOOM_STEP;
      updateDraft(bg.zoomBy(draft, factor));
    }, { passive: false });

    function handleAction(action) {
      var step = constants.OFFSET_STEP;
      switch (action) {
        case "zoom-out": updateDraft(bg.zoomBy(draft, 1 / constants.ZOOM_STEP)); break;
        case "zoom-in": updateDraft(bg.zoomBy(draft, constants.ZOOM_STEP)); break;
        case "reset":
          if (draft) {
            updateDraft({
              image: draft.image,
              width: draft.width,
              height: draft.height,
              transform: { scale: 1, offsetX: 0, offsetY: 0 }
            });
          }
          break;
        case "left": updateDraft(bg.nudgeBy(draft, -step, 0)); break;
        case "right": updateDraft(bg.nudgeBy(draft, step, 0)); break;
        case "up": updateDraft(bg.nudgeBy(draft, 0, -step)); break;
        case "down": updateDraft(bg.nudgeBy(draft, 0, step)); break;
        case "cancel": cancelEditor(); break;
        case "apply": applyEditor(); break;
      }
    }

    editor.addEventListener("click", function (event) {
      var button = event.target.closest("[data-bg-act]");
      if (!button || button.disabled) return;
      handleAction(button.getAttribute("data-bg-act"));
    });

    /* Esc = 取消：原生 dialog 的 cancel 事件,preventDefault 后走统一取消
     * 语义（restoreApplied 回退预览），不直接默认关闭。 */
    editor.addEventListener("cancel", function (event) {
      event.preventDefault();
      cancelEditor();
    });

    /* 键盘：方向键微调，+/- 缩放（编辑面打开时全局监听；Esc 由原生
     * dialog cancel 事件处理，不在此重复）。 */
    document.addEventListener("keydown", function (event) {
      if (!editorOpen || busy) return;
      var step = constants.OFFSET_STEP;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        updateDraft(bg.nudgeBy(draft, -step, 0));
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        updateDraft(bg.nudgeBy(draft, step, 0));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        updateDraft(bg.nudgeBy(draft, 0, -step));
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        updateDraft(bg.nudgeBy(draft, 0, step));
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        updateDraft(bg.zoomBy(draft, constants.ZOOM_STEP));
      } else if (event.key === "-") {
        event.preventDefault();
        updateDraft(bg.zoomBy(draft, 1 / constants.ZOOM_STEP));
      }
    });

    /* ── popover 入口：三个按钮 + 状态行（多实例同步 disabled）── */

    function popoverStatus(message) {
      document.querySelectorAll("[data-background-status]").forEach(function (node) {
        node.hidden = !message;
        node.textContent = message || "";
      });
    }

    function syncButtons() {
      var hasBackground = !!bg.applied();
      document.querySelectorAll("[data-background-edit], [data-background-clear]").forEach(function (button) {
        button.disabled = !hasBackground;
      });
    }

    document.querySelectorAll("[data-background-import]").forEach(function (button) {
      button.addEventListener("click", function () {
        popoverStatus("");
        fileInput.click();
      });
    });

    document.querySelectorAll("[data-background-edit]").forEach(function (button) {
      button.addEventListener("click", function () {
        var applied = bg.applied();
        if (!applied) return;
        popoverStatus("");
        // 重新编辑当前背景：保留已应用 transform。
        openEditor({
          image: applied.image,
          width: applied.width,
          height: applied.height,
          transform: {
            scale: applied.transform.scale,
            offsetX: applied.transform.offsetX,
            offsetY: applied.transform.offsetY
          }
        });
      });
    });

    document.querySelectorAll("[data-background-clear]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!bg.applied()) return;
        bg.clear().then(function () {
          popoverStatus("");
          syncButtons();
        }).catch(function () {
          popoverStatus(MSG_CLEAR_FAILED);
        });
      });
    });

    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (!file) return;
      popoverStatus("");
      processFile(file).then(function (record) {
        openEditor(record);
      }).catch(function (error) {
        popoverStatus(error && error.tooLarge ? MSG_TOO_LARGE : MSG_IMPORT_FAILED);
      });
    });

    // 与 bootstrap 的首读对齐后再同步按钮态（load 幂等：重读一次同一 record）。
    bg.load().then(syncButtons).catch(syncButtons);
  };
})(window, document);
