function installFirstUseFixture() {
  const fixture = {
    status: window.firstUseStatus,
    session: {configured: false},
    pairingResult: "invalid",
    readFails: false,
    ledgers: [
      {ledger_id: "family", name: "家庭账本", role: "member", is_default: true, is_current: false},
    ],
    commands: [],
  };
  window.CONTROL_TOKEN = "synthetic-control";
  window.fetch = async (path, options = {}) => {
    if (path === "/api/status") return {ok: true, json: async () => fixture.status};
    if (path === "/api/product/session") {
      if (fixture.readFails) throw new Error("synthetic unavailable");
      return {ok: true, json: async () => fixture.session};
    }
    if (path === "/api/product/ledgers") return {ok: true, json: async () => ({ledgers: fixture.ledgers})};
    if (path === "/api/open_pairing") {
      fixture.commands.push({path, method: options.method});
      return {ok: true, json: async () => fixture.status};
    }
    if (path === "/api/product/pair") {
      if (fixture.pairingResult === "invalid") {
        return {ok: false, json: async () => ({message: "绑定码无效或过期，请重新生成。"})};
      }
      fixture.session = {configured: false, pairing_recovery: "original_code_required"};
      throw new Error("synthetic response loss");
    }
    throw new Error("unexpected fixture route");
  };
  return fixture;
}

const firstUseCodeEntry = () => document.getElementById("desktopPairingCodeAction");
const firstUseEntryAvailable = () => Boolean(firstUseCodeEntry() && !firstUseCodeEntry().disabled && !firstUseCodeEntry().hidden);
const firstUseCodeEntries = () => [firstUseCodeEntry(), document.getElementById("androidAction")];

async function cannotGenerateFirstUseCode(fixture) {
  const before = fixture.commands.length;
  firstUseCodeEntries().forEach((button) => button.click());
  while (actionInFlight) await new Promise(requestAnimationFrame);
  return firstUseCodeEntries().every((button) => button.disabled) && fixture.commands.length === before;
}

async function probeFirstUseAndInvalidCode(fixture) {
  const unreadSessionClosed = await cannotGenerateFirstUseCode(fixture);
  await refresh();
  const result = {localCodeReachable: firstUseEntryAvailable(),
    unreadSessionClosed,
    deviceCodeReachableWithoutPhoneUrl: !document.getElementById("androidAction").disabled};
  if (firstUseCodeEntry()) {
    firstUseCodeEntry().click();
    while (actionInFlight) await new Promise(requestAnimationFrame);
  }
  result.localCodeCommand = fixture.commands.length === 1 && fixture.commands[0].method === "POST";
  const help = document.getElementById("productFirstUseHelp");
  result.dataAndIdentityExplained = Boolean(help && !help.hidden &&
    ["这台 Windows 电脑", "拥有者", "家庭成员", "邀请"].every((text) => help.textContent.includes(text)));
  document.getElementById("pairingCodeInput").value = "12345678";
  await pairProduct();
  result.invalidCodeRetained = document.getElementById("pairingCodeInput").value === "12345678";
  result.invalidCanGetNewCode = firstUseEntryAvailable();
  return result;
}

async function probeUnknownPairingAndExpiry(fixture, result) {
  fixture.pairingResult = "unknown";
  await pairProduct();
  result.originalCodeRetained = document.getElementById("pairingCodeInput").value === "12345678";
  result.pendingExplained = document.getElementById("productState").textContent.includes("原绑定码");
  result.pendingCannotMintNewCode = Boolean(firstUseCodeEntry() && firstUseCodeEntry().disabled);
  result.pendingClosesBothCodeEntries = await cannotGenerateFirstUseCode(fixture);
  document.getElementById("pairingCodeInput").value = "";
  productSession = null;
  await loadProductSession();
  result.restartStillExplainsOriginalCode = document.getElementById("productState").textContent.includes("原绑定码");
  fixture.session = {configured: false}; // The Controller, not a browser clock, settles expiry.
  await loadProductSession();
  result.expiredCanGetNewCode = firstUseEntryAvailable();
}

async function probePendingRebindWithLiveLedger(fixture, result) {
  fixture.session = {configured: true, account_name: "我", ledger_id: "archived", ledger_name: "原账本",
    device_name: "此电脑", role: "owner", expires_at: null, pairing_recovery: "original_code_required"};
  await loadProductSession();
  await loadProductLedgers();
  result.pendingRebindExplained = !document.getElementById("productPairGroup").hidden &&
    document.getElementById("productState").textContent.includes("原绑定码") && firstUseCodeEntry().disabled;
  fixture.ledgers = [{ledger_id: "archived", name: "原账本", role: "owner", is_default: false, is_current: true}, ...fixture.ledgers];
  document.getElementById("pairingCodeInput").value = "12345678";
  await loadProductLedgers();
  result.liveOldLedgerStillOffersOriginalCode = !document.getElementById("productPairGroup").hidden &&
    document.getElementById("productManageGroup").hidden &&
    !document.getElementById("pairingCodeInput").disabled && !document.getElementById("pairAction").disabled &&
    document.getElementById("pairingCodeInput").value === "12345678" &&
    document.getElementById("productState").textContent.includes("原绑定码");
  result.liveOldLedgerCannotMintNewCode = await cannotGenerateFirstUseCode(fixture);
  result.horizontalOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
}

async function probeReadFailureAndUnavailable(fixture, result) {
  fixture.readFails = true;
  await loadProductSession();
  result.readFailureClosed = document.getElementById("productPairGroup").hidden &&
    Boolean(firstUseCodeEntry() && firstUseCodeEntry().disabled);
  result.readFailureClosesBothCodeEntries = await cannotGenerateFirstUseCode(fixture);
  fixture.readFails = false;
  fixture.status.product_available = false;
  fixture.status.health = false;
  await refresh();
  result.unavailableClosed = Boolean(firstUseCodeEntry() && firstUseCodeEntry().disabled) &&
    document.getElementById("pairAction").disabled;
}

(async () => {
  const fixture = installFirstUseFixture();
  const result = await probeFirstUseAndInvalidCode(fixture);
  await probeUnknownPairingAndExpiry(fixture, result);
  await probePendingRebindWithLiveLedger(fixture, result);
  await probeReadFailureAndUnavailable(fixture, result);
  window.firstUseProbe = result;
})().catch(() => { window.firstUseProbe = {probeError: true}; });
