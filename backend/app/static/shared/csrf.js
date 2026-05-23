(function () {
  "use strict";

  var meta = document.querySelector('meta[name="csrf-token"]');
  var token = meta ? meta.getAttribute("content") || "" : "";
  if (!token) {
    return;
  }

  function sameOriginUrl(input) {
    try {
      var url = new URL(input, window.location.href);
      return url.origin === window.location.origin;
    } catch (_err) {
      return false;
    }
  }

  function attachFormToken(form) {
    var method = (form.getAttribute("method") || "get").toLowerCase();
    if (method !== "post") {
      return;
    }
    var existing = form.querySelector('input[name="csrf_token"]');
    if (existing) {
      existing.value = token;
      return;
    }
    var field = document.createElement("input");
    field.type = "hidden";
    field.name = "csrf_token";
    field.value = token;
    form.appendChild(field);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form").forEach(attachFormToken);
  });
  document.addEventListener("submit", function (event) {
    if (event.target && event.target.tagName === "FORM") {
      attachFormToken(event.target);
    }
  }, true);

  if (typeof window.fetch === "function") {
    var rawFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      var target = typeof input === "string" ? input : input && input.url;
      if (target && sameOriginUrl(target)) {
        init = init || {};
        var headers = new Headers(init.headers || (input && input.headers) || {});
        if (!headers.has("X-CSRF-Token")) {
          headers.set("X-CSRF-Token", token);
        }
        init.headers = headers;
      }
      return rawFetch(input, init);
    };
  }
})();
