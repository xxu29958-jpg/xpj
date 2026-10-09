(async () => {
  window.TicketboxWeb.initFormDisclosures();
  window.TicketboxWeb.initDrawer();
  const pause = () => new Promise(resolve => setTimeout(resolve, 40));
  const form = document.querySelector("form.edit-form");
  const items = document.querySelector('#expense-items form[action$="/items/save"]');
  const put = (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event("input", {bubbles: true}));
  };
  const leaving = () => {
    const event = new Event("beforeunload", {cancelable: true});
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };
  document.querySelector('a.review-subtask-link[href$="#expense-items"]').click();
  await pause();
  const result = {
    detailsVisible: !document.querySelector("[data-review-subtasks]").hidden,
    mainHidden: document.querySelector(".expense-detail-layout").hidden,
  };
  put(items.querySelector('[name="item_name"]'), "原明细修改");
  put(items.querySelector('[name="item_amount_yuan"]'), "000100.00");
  put(items.querySelectorAll('[name="item_name"]')[3], "第三个新增位");
  location.hash = "#review";
  await pause();
  result.mainVisibleOnReturn = !document.querySelector(".expense-detail-layout").hidden;
  location.hash = "#expense-items";
  await pause();
  result.names = new FormData(items).getAll("item_name");
  result.amountText = items.querySelector('[data-review-value="item_amount_yuan"]').textContent;
  result.summaryText = items.querySelector('[data-review-value="item_name"]').textContent;
  // Native navigation may occur after the submit-event task. Do not expire its
  // identity before beforeunload, or the submitted section warns about itself.
  items.dispatchEvent(new SubmitEvent("submit", {bubbles: true, cancelable: true}));
  await pause();
  result.ownSubmitWarned = leaving();
  put(form.elements.namedItem("merchant"), "未提交的原商家");
  items.dispatchEvent(new SubmitEvent("submit", {bubbles: true, cancelable: true}));
  await pause();
  result.otherInputWarned = leaving();
  result.cancelThenLeaveWarned = leaving();
  result.merchant = form.elements.namedItem("merchant").value;
  result.version = form.elements.namedItem("expected_row_version").value;
  result.action = items.action;
  window.__webConsumerProbe = result;
})().catch(error => { window.__webConsumerProbe = {error: String(error), stack: error.stack}; });
