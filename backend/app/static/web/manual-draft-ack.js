/* A full native landing renders this only for a canonical manual Expense. */
(function (window, document) {
  "use strict";
  const marker = document.querySelector("[data-manual-draft-ack]");
  if (!marker || !window.navigator.locks) return;
  const drafts = window.TicketboxManualDrafts;
  const status = document.querySelector("[data-manual-draft-ack-status]");
  Promise.resolve().then(function () {
    const ack = JSON.parse(marker.getAttribute("data-manual-draft-ack"));
    return window.navigator.locks.request(drafts.key(ack.clientRef), function () {
      drafts.acknowledge(ack);
    });
  }).catch(function () {
    status.textContent = "这笔记录已保存，但浏览器里的草稿暂未收起。可稍后重新打开此记录。";
    status.hidden = false;
  });
})(window, document);
