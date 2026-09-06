# Desktop first use and pairing continuation

This bounded slice implements the active whole-system Goal and the September 6 capability-first ruling. It does not replace the full Internal Beta RC goal. Product identity and the final Product/Windows/post-G2 contracts remain the authority; existing UI and tests are evidence.

## User outcome and scope

A healthy local installation lets its Owner reach the existing code-generation task directly from the unbound Desktop entry, even without a phone connection URL. The entry explains that the Windows computer stores the household data and originals. It distinguishes an Owner's own device binding, a household member's personal device authorization, and invitation-based household entry.

A rejected fresh code leaves entered text available for correction and allows a new code. An unknown pair result keeps its original durable proof and tells the user to continue with the original code. That explanation survives a Manager restart through the Controller's non-secret projection. If the original code is lost, the pending attempt must finish expiring before a new code can start; passive refresh may observe that transition, but never spends a provisional proof. A new mismatched code must not erase or replace a possibly committed attempt.

Allowed changes are the actual Manager HTML entry and feedback, the Controller's non-secret projection and actionable error, and directly related tests. Backend identity/code/activation ownership, WinCred encoding, proof lifetime, teardown, account membership and permissions remain with their existing owners. No secret or entered code is copied into browser storage or status. No new auth protocol, public connectivity mutation, installer operation or held Windows lifecycle is introduced.

## Producer, consumer and retirement

- Backend identity and Owner/personal device authorization remain the only code/identity owners.
- `AppController.open_pairing` opens the existing loopback Owner task. Its availability follows local product readiness; a phone URL is not required for local binding.
- Existing WinCred recovery supplies only an `original_code_required` state to the Manager. The proof and any credential remain private to their current owners.
- The actual Manager preserves input on rejection or unknown result, gives truthful continuation, and keeps unavailable/session-read failures closed. Current roles continue to come from live membership.
- Installer-only instructions, the phone-dependent gate on the local code action, and the generic regenerate-code advice for a reused pending attempt retire.

## Minimal evidence and exit

The current Controller recovery test must fail when a restarted Manager cannot explain an unspent pending attempt; its existing same-proof replay and terminal/fresh-invalid cases remain meaningful. A real Edge execution of the production HTML must fail when a healthy local-only installation cannot reach the code command, unknown-result feedback loses the original context, or a failed state read enables binding. Synthetic providers isolate these UI observations; they do not prove a live backend ceremony.

Run short Controller and Edge tests locally, then the final candidate's relevant CI/CodeQL/scope gates and existing real backend Desktop lane in the cloud. Complete bounded source review, normal protected integration and independent main qualification. Actual clean-Windows Setup/APK and full cross-client RC rehearsal remain the original Goal's later gates. No ten-minute-scale local test and no #372 detail work.

Current evidence: both Controller continuation cases and the real Edge first-use case reproduced RED on the previous production source. A second Edge RED showed the shared device-code action still incorrectly depended on the phone URL; that gate is retired too. The corrected consumer passes 82 short Controller, static and real Edge regression cases in approximately four seconds, including invalid/unknown/expired/read-failed states, existing binding lifetimes and role/visibility behavior. An actual 820-pixel frame was inspected; the first-use probe also runs at 390 pixels. Synthetic providers bound these observations; cloud and live-backend qualification remain pending.
