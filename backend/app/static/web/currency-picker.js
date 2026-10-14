/* Enhance existing native currency selects; the original control owns the value. */
(() => {
  "use strict";
  const script = document.currentScript;
  const names = JSON.parse(script.dataset.currencyNames || "{}");
  document.querySelectorAll("select[name]").forEach(select => {
    if (!/currency/.test(select.name)) return;
    const options = Array.from(select.options);
    if (options.filter(option => names[option.value]).length < 10) return;
    options.forEach(option => {
      if (names[option.value] && option.textContent.trim() === option.value) {
        option.textContent = option.value + " · " + names[option.value];
      }
    });
    const search = document.createElement("input");
    search.type = "search";
    search.className = select.className;
    search.placeholder = "搜索币种名称或代码";
    search.setAttribute("aria-label", "搜索币种名称或代码");
    search.autocomplete = "off";
    search.disabled = select.disabled;
    search.addEventListener("input", () => {
      const query = search.value.trim().toLocaleUpperCase();
      options.forEach(option => {
        option.hidden = Boolean(query) && option.value !== select.value && option.value !== "" &&
          !(option.textContent + " " + (names[option.value] || "")).toLocaleUpperCase().includes(query);
      });
    });
    select.before(search);
  });
})();
