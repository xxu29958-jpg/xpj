(function () {
  "use strict";
  const field = document.querySelector("[data-settings-code]");
  const button = document.querySelector("[data-settings-copy]");
  const status = document.querySelector("[data-settings-copy-status]");
  if (!field || !button || !status) return;
  button.addEventListener("click", async function () {
    try {
      await navigator.clipboard.writeText(field.value);
      status.textContent = "连接码已复制，请在自己的另一台设备上输入。";
    } catch (_) {
      field.focus();
      field.select();
      status.textContent = "已选中连接码，请手动复制。";
    }
  });
  window.addEventListener("pagehide", function () {
    field.value = "";
    document.querySelector("[data-settings-code-result]").hidden = true;
  });
})();
