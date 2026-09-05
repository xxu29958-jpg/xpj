/* 外观本地偏好合同 + anti-FOUC bootstrap — base.html 与 auth/login.html 共享。
 *
 * TicketboxAppearance 是质感 (ui-texture) 与强调色 (ui-accent) 两条本地轴的
 * 唯一合同 owner: storage key、合法值、默认值只在此声明一份。本脚本在首帧
 * 前经它还原 <html data-*>; theme.js 运行时经同一合同读/写/应用, 不再复制
 * 第二份常量。两条轴无 SSR cookie、不登录、不上传、不跨端同步。
 *
 * 必须是**无 defer 的外部脚本**: CSP script-src 'self' 会阻断一切 inline
 * script; defer 则晚于首帧, 失去 anti-FOUC 意义。
 */
(function (window, document) {
  "use strict";

  var AXES = {
    texture: { storageKey: "ui-texture", attr: "data-texture", values: ["flat", "fiber"], fallback: "flat" },
    accent: { storageKey: "ui-accent", attr: "data-accent", values: ["evergreen", "ink", "ochre", "plum"], fallback: "evergreen" }
  };

  function stored(axis) {
    // 只返回用户显式存过的合法值; 无偏好/非法值返回 null (不等于默认回落,
    // 让调用方区分「用户没选过」与「用户选了默认值」)。
    var spec = AXES[axis];
    var saved = null;
    try { saved = window.localStorage.getItem(spec.storageKey); } catch (_) {}
    return spec.values.indexOf(saved) !== -1 ? saved : null;
  }

  window.TicketboxAppearance = {
    read: function read(axis) {
      // 运行时读取: 无显式偏好回落默认 (flat / evergreen)。
      return stored(axis) || AXES[axis].fallback;
    },
    write: function write(axis, value) {
      var spec = AXES[axis];
      if (spec.values.indexOf(value) === -1) value = spec.fallback;
      try { window.localStorage.setItem(spec.storageKey, value); } catch (_) {}
      return value;
    },
    apply: function apply(root, axis, value) {
      root.setAttribute(AXES[axis].attr, value);
    }
  };

  // anti-FOUC: 只还原显式偏好; 无偏好时不写属性, tokens.css 的 :root 默认
  // (flat / evergreen) 生效, 与 SSR 语义一致。
  var root = document.documentElement;
  ["texture", "accent"].forEach(function (axis) {
    var value = stored(axis);
    if (value) window.TicketboxAppearance.apply(root, axis, value);
  });

  /* ── 自定义背景（全局背景批）──────────────────────────────────────
   * 单一 IDB record { image: dataURL, width, height, transform } 是唯一本地
   * 事实；读 / 写 / 渲染 owner 都在此 (TicketboxBackground)，内页与
   * auth/login 同一管线。渲染 = <html data-user-bg> + --surface-user-image*
   * 三个 var，由 shell.css / auth-login.css 的 body::before 固定层消费；
   * 取景以可见视口 (window.innerWidth/Height) 为准，页面内容伸长 / 换路由
   * 不改变构图。dataURL 渲染：CSP img-src 已允许 data:，零安全头变更；
   * 明确不使用 blob: objectURL（会被 img-src 阻断，且有生命周期问题）。
   * IDB 只能异步，无法参与上面的 anti-FOUC 首帧；读取完成后 CSS 淡入，
   * 是诚实代价，不为此另造 localStorage 第二 authority。
   */
  var BG_DB_NAME = "ticketbox-appearance";
  var BG_DB_VERSION = 1;
  var BG_STORE = "background";
  var BG_KEY = "current";
  var BG_MIN_SCALE = 1;
  var BG_MAX_SCALE = 3;
  var BG_OFFSET_LIMIT = 1;
  // 与 Android BackgroundTransformGeometry 同值, 两端手感一致。
  var BG_OFFSET_STEP = 0.08;
  var BG_ZOOM_STEP = 1.12;

  // bgApplied = 已提交事实; bgRendered = 当前上屏记录 (预览时 = draft)。
  var bgApplied = null;
  var bgRendered = null;

  function bgClamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function bgNormalize(record) {
    if (!record || typeof record.image !== "string" || record.image.indexOf("data:") !== 0) return null;
    if (!(record.width > 0) || !(record.height > 0)) return null;
    var t = record.transform || {};
    return {
      image: record.image,
      width: record.width,
      height: record.height,
      transform: {
        scale: bgClamp(typeof t.scale === "number" ? t.scale : 1, BG_MIN_SCALE, BG_MAX_SCALE),
        offsetX: bgClamp(typeof t.offsetX === "number" ? t.offsetX : 0, -BG_OFFSET_LIMIT, BG_OFFSET_LIMIT),
        offsetY: bgClamp(typeof t.offsetY === "number" ? t.offsetY : 0, -BG_OFFSET_LIMIT, BG_OFFSET_LIMIT)
      }
    };
  }

  function bgOpenDb() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) {
        reject(new Error("indexedDB unavailable"));
        return;
      }
      var request = window.indexedDB.open(BG_DB_NAME, BG_DB_VERSION);
      request.onupgradeneeded = function () {
        var db = request.result;
        if (!db.objectStoreNames.contains(BG_STORE)) db.createObjectStore(BG_STORE);
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error || new Error("idb open failed")); };
    });
  }

  function bgTx(mode, run) {
    return bgOpenDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var request = null;
        var tx = db.transaction(BG_STORE, mode);
        tx.oncomplete = function () {
          db.close();
          resolve(request ? request.result : undefined);
        };
        tx.onerror = function () {
          db.close();
          reject(tx.error || new Error("idb tx failed"));
        };
        tx.onabort = function () {
          db.close();
          reject(tx.error || new Error("idb tx aborted"));
        };
        request = run(tx.objectStore(BG_STORE));
      });
    });
  }

  function bgViewport() {
    return { width: window.innerWidth || 0, height: window.innerHeight || 0 };
  }

  // cover 基准: 图按 viewport/image 最大比放大后恰好填满视口, transform.scale
  // 在其上再放大; offset ∈ [-1,1] 是可平移余量的归一化比例, 实际平移
  // translation = -offset × maxTranslation (与 Android renderer 同语义)。
  function bgMetrics(record, viewport) {
    if (!viewport.width || !viewport.height) return null;
    var cover = Math.max(viewport.width / record.width, viewport.height / record.height);
    var w = record.width * cover * record.transform.scale;
    var h = record.height * cover * record.transform.scale;
    return {
      width: w,
      height: h,
      maxX: Math.max(0, (w - viewport.width) / 2),
      maxY: Math.max(0, (h - viewport.height) / 2)
    };
  }

  function bgRender(record) {
    bgRendered = record;
    var metrics = record ? bgMetrics(record, bgViewport()) : null;
    if (!metrics) {
      root.removeAttribute("data-user-bg");
      root.style.removeProperty("--surface-user-image");
      root.style.removeProperty("--surface-user-image-size");
      root.style.removeProperty("--surface-user-image-position");
      return;
    }
    var tx = -record.transform.offsetX * metrics.maxX;
    var ty = -record.transform.offsetY * metrics.maxY;
    root.style.setProperty("--surface-user-image", 'url("' + record.image + '")');
    root.style.setProperty(
      "--surface-user-image-size",
      metrics.width.toFixed(1) + "px " + metrics.height.toFixed(1) + "px"
    );
    root.style.setProperty(
      "--surface-user-image-position",
      "calc(50% + " + tx.toFixed(1) + "px) calc(50% + " + ty.toFixed(1) + "px)"
    );
    root.setAttribute("data-user-bg", "");
  }

  window.TicketboxBackground = {
    constants: {
      MIN_SCALE: BG_MIN_SCALE,
      MAX_SCALE: BG_MAX_SCALE,
      OFFSET_STEP: BG_OFFSET_STEP,
      ZOOM_STEP: BG_ZOOM_STEP
    },
    applied: function () { return bgApplied; },
    load: function () {
      return bgTx("readonly", function (store) { return store.get(BG_KEY); }).then(function (raw) {
        bgApplied = bgNormalize(raw);
        bgRender(bgApplied);
        return bgApplied;
      });
    },
    // 预览只上屏, 不写 IDB、不动 bgApplied; 取消经 restoreApplied 还原。
    preview: function (draft) {
      var record = bgNormalize(draft);
      if (record) bgRender(record);
    },
    restoreApplied: function () {
      bgRender(bgApplied);
    },
    // 应用 = 单一 record 单事务提交; 只有 commit 成功才把 draft 转正为
    // current。失败 reject, 调用方保留草稿继续编辑。
    apply: function (draft) {
      var record = bgNormalize(draft);
      if (!record) return Promise.reject(new Error("background draft invalid"));
      return bgTx("readwrite", function (store) { return store.put(record, BG_KEY); }).then(function () {
        bgApplied = record;
        bgRender(record);
        return record;
      });
    },
    clear: function () {
      return bgTx("readwrite", function (store) { return store.delete(BG_KEY); }).then(function () {
        bgApplied = null;
        bgRender(null);
      });
    },
    // 纯几何换算 (不写屏): 编辑器手势 / 按钮共用, 各自不许猜像素。
    panBy: function (record, dxPx, dyPx) {
      var next = bgNormalize(record);
      if (!next) return record;
      var metrics = bgMetrics(next, bgViewport());
      if (!metrics) return record;
      next.transform.offsetX = bgClamp(
        next.transform.offsetX + (metrics.maxX > 0 ? -dxPx / metrics.maxX : 0),
        -BG_OFFSET_LIMIT, BG_OFFSET_LIMIT
      );
      next.transform.offsetY = bgClamp(
        next.transform.offsetY + (metrics.maxY > 0 ? -dyPx / metrics.maxY : 0),
        -BG_OFFSET_LIMIT, BG_OFFSET_LIMIT
      );
      return next;
    },
    zoomBy: function (record, factor) {
      var next = bgNormalize(record);
      if (!next) return record;
      next.transform.scale = bgClamp(next.transform.scale * factor, BG_MIN_SCALE, BG_MAX_SCALE);
      return next;
    },
    nudgeBy: function (record, dx, dy) {
      var next = bgNormalize(record);
      if (!next) return record;
      next.transform.offsetX = bgClamp(next.transform.offsetX + dx, -BG_OFFSET_LIMIT, BG_OFFSET_LIMIT);
      next.transform.offsetY = bgClamp(next.transform.offsetY + dy, -BG_OFFSET_LIMIT, BG_OFFSET_LIMIT);
      return next;
    }
  };

  // 首读: 异步不阻塞首帧; 失败 (IDB 不可用 / 记录损坏) 诚实保持主题背景。
  window.TicketboxBackground.load().catch(function () {});
  // 视口变化 (resize / 旋转) 以同一 record 重算取景, 不改变用户构图语义。
  var bgResizeTimer = null;
  window.addEventListener("resize", function () {
    if (!bgRendered) return;
    if (bgResizeTimer) window.clearTimeout(bgResizeTimer);
    bgResizeTimer = window.setTimeout(function () {
      if (bgRendered) bgRender(bgRendered);
    }, 120);
  });
})(window, document);
