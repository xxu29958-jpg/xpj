(async () => {
  const status = window.firstUseStatus;
  let session = {configured: false};
  let pairingResult = "invalid";
  let readFails = false;
  const commands = [];
  window.CONTROL_TOKEN = "synthetic-control";
  window.fetch = async (path, options = {}) => {
    if (path === "/api/status") return {ok: true, json: async () => status};
    if (path === "/api/product/session") {
      if (readFails) throw new Error("synthetic unavailable");
      return {ok: true, json: async () => session};
    }
    if (path === "/api/open_pairing") {
      commands.push({path, method: options.method});
      return {ok: true, json: async () => status};
    }
    if (path === "/api/product/pair") {
      if (pairingResult === "invalid") {
        return {ok: false, json: async () => ({message: "绑定码无效或过期，请重新生成。"})};
      }
      session = {configured: false, pairing_recovery: "original_code_required"};
      throw new Error("synthetic response loss");
    }
    throw new Error("unexpected fixture route");
  };
  const codeEntry = () => document.getElementById("desktopPairingCodeAction");
  const entryAvailable = () => Boolean(codeEntry() && !codeEntry().disabled && !codeEntry().hidden);
  await refresh();
  const result = {localCodeReachable: entryAvailable(),
    deviceCodeReachableWithoutPhoneUrl: !document.getElementById("androidAction").disabled};
  if (codeEntry()) {
    codeEntry().click();
    while (actionInFlight) await new Promise(requestAnimationFrame);
  }
  result.localCodeCommand = commands.length === 1 && commands[0].method === "POST";
  const help = document.getElementById("productFirstUseHelp");
  result.dataAndIdentityExplained = Boolean(help && !help.hidden &&
    ["这台 Windows 电脑", "拥有者", "家庭成员", "邀请"].every((text) => help.textContent.includes(text)));
  document.getElementById("pairingCodeInput").value = "12345678";
  await pairProduct();
  result.invalidCodeRetained = document.getElementById("pairingCodeInput").value === "12345678";
  result.invalidCanGetNewCode = entryAvailable();
  pairingResult = "unknown";
  await pairProduct();
  result.originalCodeRetained = document.getElementById("pairingCodeInput").value === "12345678";
  result.pendingExplained = document.getElementById("productState").textContent.includes("原绑定码");
  result.pendingCannotMintNewCode = Boolean(codeEntry() && codeEntry().disabled);
  document.getElementById("pairingCodeInput").value = "";
  productSession = null;
  await loadProductSession();
  result.restartStillExplainsOriginalCode = document.getElementById("productState").textContent.includes("原绑定码");
  session = {configured: false}; // The Controller, not a browser clock, settles expiry.
  await loadProductSession();
  result.expiredCanGetNewCode = entryAvailable();
  result.horizontalOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
  readFails = true;
  await loadProductSession();
  result.readFailureClosed = document.getElementById("productPairGroup").hidden &&
    Boolean(codeEntry() && codeEntry().disabled);
  readFails = false;
  status.product_available = false;
  status.health = false;
  await refresh();
  result.unavailableClosed = Boolean(codeEntry() && codeEntry().disabled) &&
    document.getElementById("pairAction").disabled;
  window.firstUseProbe = result;
})().catch(() => { window.firstUseProbe = {probeError: true}; });
