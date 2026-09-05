/* Browser-local unsubmitted intent storage. No money rules, credentials or IO to
 * the server. Callers hold the exclusive per-intent Web Lock while mutating. */
(function (window) {
  "use strict";
  const prefix = "ticketbox:manual-draft:v1:";
  const fields = ["amount_major", "currency_code", "merchant", "category", "spent_at", "note"];
  const axes = ["datasetId", "clientGeneration", "accountId", "ledgerId", "deviceId"];

  function key(ref) {
    if (typeof ref !== "string" || !/^[a-f0-9]{32}$/.test(ref)) throw Error("invalid_draft_ref");
    return prefix + ref;
  }

  function matches(left, right, includeDevice = true) {
    return axes.every(axis => (!includeDevice && axis === "deviceId") || left[axis] === right[axis]);
  }

  function scopeValue(scope) {
    const result = {};
    axes.forEach(axis => {
      if (typeof scope[axis] !== "string" || !scope[axis] || scope[axis].length > 256) {
        throw Error("invalid_draft_scope");
      }
      result[axis] = scope[axis];
    });
    return result;
  }

  function fieldValues(values) {
    const result = {};
    fields.forEach(name => {
      if (typeof values[name] !== "string") throw Error("invalid_draft_fields");
      result[name] = values[name];
    });
    return result;
  }

  function read(ref) {
    const raw = window.localStorage.getItem(key(ref));
    if (raw === null) return null;
    if (raw.length > 131072) throw Error("draft_too_large");
    const record = JSON.parse(raw);
    if (record.version !== 1 || record.clientRef !== ref ||
        !["editing", "submitted", "blocked"].includes(record.phase) ||
        !Number.isFinite(record.updatedAt)) throw Error("unsupported_draft");
    scopeValue(record.scope);
    fieldValues(record.values);
    return record;
  }

  function save(scope, ref, phase, values, serverResult = "") {
    const next = {version: 1, scope: scopeValue(scope), clientRef: ref, phase,
      values: fieldValues(values), updatedAt: Date.now()};
    if (!["editing", "submitted", "blocked"].includes(phase)) throw Error("invalid_draft_phase");
    const previous = read(ref);
    if (previous && !matches(previous.scope, next.scope)) throw Error("draft_binding_changed");
    if (previous && previous.phase !== "editing" && serverResult !== "rejected") {
      if (phase === "editing" || JSON.stringify(fieldValues(previous.values)) !== JSON.stringify(next.values)) {
        throw Error("submitted_snapshot_is_immutable");
      }
    }
    const raw = JSON.stringify(next);
    if (raw.length > 131072) throw Error("draft_too_large");
    window.localStorage.setItem(key(ref), raw);
    return next;
  }

  function list(scope) {
    const records = [];
    const storage = window.localStorage;
    for (let index = 0; index < storage.length; index += 1) {
      const name = storage.key(index);
      if (!name || !name.startsWith(prefix)) continue;
      const record = read(name.slice(prefix.length));
      if (record && matches(record.scope, scope, false)) records.push(record);
    }
    return records.sort((left, right) => right.updatedAt - left.updatedAt);
  }

  function acknowledge(ack) {
    const record = read(ack.clientRef);
    if (!record || !matches(record.scope, scopeValue(ack.scope))) return false;
    window.localStorage.removeItem(key(ack.clientRef));
    return true;
  }

  window.TicketboxManualDrafts = {fields, key, matches, read, save, list, acknowledge};
})(window);
