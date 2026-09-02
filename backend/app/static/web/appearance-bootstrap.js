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
    texture: { storageKey: "ui-texture", attr: "data-texture", values: ["flat", "fiber"], fallback: "fiber" },
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
      // 运行时读取: 无显式偏好回落默认 (fiber / evergreen)。
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
  // (fiber / evergreen) 生效, 与 SSR 语义一致。
  var root = document.documentElement;
  ["texture", "accent"].forEach(function (axis) {
    var value = stored(axis);
    if (value) window.TicketboxAppearance.apply(root, axis, value);
  });
})(window, document);
