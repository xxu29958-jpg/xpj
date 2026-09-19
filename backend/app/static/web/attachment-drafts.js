/* Attachment intent adapter of the existing draft state machine. Callers hold
 * the same per-intent Web Lock across selection, sending and acknowledgement. */
(function (window) {
  "use strict";
  const store = window.TicketboxDraftStore.createStore({
    prefix: "ticketbox:attachment-draft:v1:", validRef: /^[a-f0-9]{32}$/,
    fields: ["action", "reviewed_sha256", "request_id", "file_sha256", "file_name", "file_type", "file_last_modified"],
  });
  function validateAction(scope, ref, values) {
    const url = new URL(values.action, window.location.href);
    const allowed = /^\/web\/(pending\/upload|expenses\/[1-9]\d*\/original\/(verify|replenish|cleanup\/(retry|cancel)))$/;
    if (url.origin !== window.location.origin || !allowed.test(url.pathname) ||
        url.searchParams.get("idempotency_key") !== ref || url.searchParams.get("ledger_id") !== scope.ledgerId ||
        !store.matches(JSON.parse(url.searchParams.get("draft_scope")), scope)) throw Error("invalid_attachment_target");
  }
  async function retain(scope, ref, values, file) {
    validateAction(scope, ref, values);
    const previous = store.read(ref);
    if (previous && (!store.matches(previous.scope, scope) || previous.phase !== "editing")) {
      throw Error("submitted_snapshot_is_immutable");
    }
    const meta = file ? await window.TicketboxDraftFiles.put(store.key(ref), scope, file) : {};
    return store.save(scope, ref, "editing", {...values, ...meta});
  }
  async function submitted(scope, ref) {
    const record = store.read(ref);
    if (!record || !store.matches(record.scope, scope)) throw Error("draft_binding_changed");
    validateAction(scope, ref, record.values);
    const file = record.values.file_sha256 ? await window.TicketboxDraftFiles.get(
      store.key(ref), scope, record.values, store.matches) : null;
    return {record: store.save(scope, ref, "submitted", record.values), file};
  }
  async function acknowledge(ack) {
    // Remove the accepted intent first. A Blob cleanup failure cannot reopen it.
    if (!store.acknowledge(ack)) return false;
    await window.TicketboxDraftFiles.remove(store.key(ack.clientRef));
    return true;
  }
  window.TicketboxAttachmentDrafts = {store, retain, submitted, acknowledge};
})(window);
