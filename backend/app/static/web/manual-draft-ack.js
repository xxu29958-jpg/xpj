/* Native landing emits this only after reading the original creation receipt. */
(function (window, document) {
  "use strict";
  const marker = document.querySelector("[data-manual-draft-ack]");
  if (!marker || !window.navigator.locks) return;
  const drafts = window.TicketboxManualDrafts;
  const status = document.querySelector("[data-manual-draft-ack-status]");
  Promise.resolve().then(function () {
    const ack = JSON.parse(marker.getAttribute("data-manual-draft-ack"));
    return window.navigator.locks.request(drafts.key(ack.clientRef), async function () {
      const href = await window.TicketboxManualOriginal.handoff(ack);
      if (href) {
        const link = document.querySelector("[data-manual-original-continue]");
        link.href = href;
        link.hidden = false;
        status.textContent = "账单已保存。所选图片已保留，继续核对后即可添加。";
        status.hidden = false;
      }
      if (drafts.acknowledge(ack)) {
        await window.TicketboxDraftFiles.remove(drafts.key(ack.clientRef));
      }
    });
  }).catch(function () {
    const link = document.querySelector("[data-manual-original-continue]");
    if (link.hidden) {
      link.href = window.location.href;
      link.textContent = "重试接续原稿";
      link.hidden = false;
      status.textContent = "账单已保存，原稿暂未接续完成。请保留浏览器数据，恢复存储后重试；不会重复创建账单。";
    } else {
      status.textContent = "账单与所选图片已保留，旧草稿文件暂未收起。可以继续添加原件。";
    }
    status.hidden = false;
  });
})(window, document);
