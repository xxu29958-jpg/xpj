/* Blob accompaniment to TicketboxDraftStore keys, never a command queue.
 * Publish the string intent only after the IndexedDB transaction completes. */
(function (window) {
  "use strict";
  function open() {
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open("ticketbox-draft-files", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("files");
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(Error("file_store_blocked"));
      request.onsuccess = () => resolve(request.result);
    });
  }
  async function transact(mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("files", mode);
      let result;
      transaction.oncomplete = () => { db.close(); resolve(result); };
      transaction.onabort = () => { db.close(); reject(transaction.error || Error("file_store_aborted")); };
      transaction.onerror = () => { /* onabort owns the final transaction result. */ };
      try { action(transaction.objectStore("files"), value => { result = value; }); }
      catch (error) { transaction.abort(); reject(error); }
    });
  }
  async function put(key, scope, file) {
    const bytes = await file.arrayBuffer();
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
    const meta = {file_sha256: sha256, file_name: file.name, file_type: file.type,
      file_last_modified: String(file.lastModified)};
    await transact("readwrite", store => store.put({scope, blob: file}, key + ":" + sha256));
    return meta;
  }
  async function get(key, scope, values, matches) {
    const item = await transact("readonly", (store, done) => {
      const request = store.get(key + ":" + values.file_sha256);
      request.onsuccess = () => done(request.result);
    });
    if (!item || !matches(item.scope, scope)) throw Error("original_file_unavailable");
    return new window.File([item.blob], values.file_name,
      {type: values.file_type, lastModified: Number(values.file_last_modified)});
  }
  function remove(key) {
    return transact("readwrite", store => {
      const request = store.openCursor(window.IDBKeyRange.bound(key + ":", key + ":\uffff"));
      request.onsuccess = () => {
        const cursor = request.result;
        if (cursor) { cursor.delete(); cursor.continue(); }
      };
    });
  }
  window.TicketboxDraftFiles = {put, get, remove};
})(window);
