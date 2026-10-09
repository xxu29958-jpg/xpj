/* A manual draft's optional file becomes an existing attachment intent only
 * after its authenticated first creation receipt. This adapter sends no command. */
(function (window) {
  "use strict";
  const manual = window.TicketboxManualDrafts;
  const attachments = window.TicketboxAttachmentDrafts;
  const files = window.TicketboxDraftFiles;
  function read(scope, ref, metadata) {
    return metadata ? files.get(manual.key(ref), scope, JSON.parse(metadata), manual.matches) : Promise.resolve(null);
  }
  async function retain(scope, ref, file) {
    return JSON.stringify(await files.put(manual.key(ref), scope, file));
  }
  async function handoff(ack) {
    const record = manual.read(ack.clientRef);
    const task = attachments.store.read(ack.clientRef);
    if (!record && (!task || !manual.matches(task.scope, ack.scope))) return null;
    if (record && (!manual.matches(record.scope, ack.scope) || !record.values.original_file)) return null;
    const target = ack.originalTarget;
    if (!target || !Number.isSafeInteger(target.expenseId) || !Number.isSafeInteger(target.rowVersion)) {
      throw Error("original_receipt_target_missing");
    }
    const action = new URL("/web/expenses/" + target.expenseId + "/original/attach", window.location.origin);
    action.search = new URLSearchParams({ledger_id: ack.scope.ledgerId, draft_scope: JSON.stringify(ack.scope),
      idempotency_key: ack.clientRef, expected_row_version: String(target.rowVersion)});
    await window.navigator.locks.request(attachments.store.key(ack.clientRef), {ifAvailable: true}, async lock => {
      if (!lock) throw Error("original_task_busy");
      const existing = attachments.store.read(ack.clientRef);
      if (existing) {
        if (!manual.matches(existing.scope, ack.scope) || new URL(existing.values.action).pathname !== action.pathname) throw Error("original_task_changed");
        if (record && (existing.values.action !== action.href ||
            existing.values.file_sha256 !== JSON.parse(record.values.original_file).file_sha256)) throw Error("original_task_changed");
        await attachments.readSource(ack.scope, ack.clientRef);
      } else {
        if (!record) throw Error("original_task_removed");
        const file = await read(ack.scope, ack.clientRef, record.values.original_file);
        await attachments.retain(ack.scope, ack.clientRef, {action: action.href, reviewed_sha256: "", request_id: ""}, file);
      }
    });
    return "/web/expenses/" + target.expenseId + "/original?ledger_id=" + encodeURIComponent(ack.scope.ledgerId) + "#attachment-" + ack.clientRef;
  }
  window.TicketboxManualOriginal = {read, retain, handoff};
})(window);
