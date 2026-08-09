# Ticketbox clean-Windows evidence harness

This branch-only harness does not rebuild Ticketbox and is not a product
candidate. It downloads artifact `9043258694` from qualification run
`31331708842`, verifies the accepted publish unit byte-for-byte, and runs two
bounded interactive scenarios on separate fresh GitHub-hosted Windows VMs:

1. a zero-state first install;
2. a process-death interruption after the durable fresh intent, followed by a
   no-clean retry of the same EXE and verification of the same operation ID.

The product source candidate remains
`7eb77f1dffed743dc84332539cb696dbe539cd41`. The qualification checkout is
`826521709c5220ec00987625b01f80117759c9aa`; both have tree
`7fd19279d5eb72a31b395a5ef634d03484f2689c`.

All waits have explicit deadlines. Installer navigation uses Windows UI
Automation control types and invoke/value/toggle patterns; it never uses screen
coordinates or silent install switches. The one-time pairing code is retained
only in process memory, is consumed by a temporary standard-user Manager
session, and is scanned out of all text evidence before upload.

The successful first-install scenario also performs one bounded SCM stop/start
cycle and proves the installation identity and PostgreSQL system identifier
survive it. Database inspection uses a short-lived, ACL-restricted libpq
passfile outside the evidence tree; the passfile is removed before upload.

## Official semantics used by the harness

- GitHub documents that every standard hosted job receives a new VM and that
  Windows hosted VMs run as administrators with UAC disabled. Therefore the
  zero-state check proves product absence, while a separate temporary standard
  user and semantic desktop probe prove the non-administrator GUI path:
  https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- Inno Setup defines `/LOG="filename"` as interactive setup logging and defines
  `/SILENT` and `/VERYSILENT` as wizard-hiding modes. This harness passes only
  `/LOG`, drives the visible wizard, and evaluates the documented exit code:
  https://jrsoftware.org/ishelp/topic_setupcmdline.htm
  https://jrsoftware.org/ishelp/topic_setupexitcodes.htm
  https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm
- Windows defines `NT AUTHORITY\LocalService` as the low-privilege SCM logon
  account. A service SID is a separate token/ACL principal; unrestricted means
  the per-service SID is present in the process token. The harness verifies both
  facts independently through SCM evidence:
  https://learn.microsoft.com/en-us/windows/win32/services/localservice-account
  https://learn.microsoft.com/en-us/windows/win32/services/service-user-accounts
  https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_sid_info
- Microsoft UI Automation defines control types and control patterns as the
  cross-framework testing surface. Installer and Manager automation therefore
  use semantic elements plus Invoke/Value/Toggle patterns, never coordinates:
  https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/using-ui-automation-for-automated-testing
- PostgreSQL libpq defines `passfile`/`PGPASSFILE` for connection passwords.
  The harness uses that mechanism instead of `PGPASSWORD`, protects the file
  with an explicit ACL, and destroys it before evidence publication:
  https://www.postgresql.org/docs/17/libpq-connect.html
  https://www.postgresql.org/docs/17/libpq-pgpass.html
