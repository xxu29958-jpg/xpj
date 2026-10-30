# 公网路径与方法清单

由 `backend/scripts/public_route_catalog.py` 经 `backend/scripts/render_public_routes.py` 生成。
这是审核后的路径策略，不是自动公开 OpenAPI。新增路由必须明确分类；测试比较真实注册路由与此清单。

Cloudflare ingress 只匹配 hostname/path；方法、鉴权、角色、账本隔离与 CSRF 继续由 Backend 执行。
静态资源仅允许 `GET/HEAD /static/web/*` 与 `/static/shared/*`；不允许 `/static/owner/*`、上传目录、文档或 metrics。
远端必须保留公网 Host，不得设置 loopback Host override。可选 Access 只覆盖 Web 和其静态资源，不能挑战原生 API 或 UploadLink。

| 方法 | 路径 | 公网 | 鉴权/责任 |
| --- | --- | --- | --- |
| GET | `/api/admin/devices` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/admin/devices/{public_id}/rename` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/admin/devices/{public_id}/revoke` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/api/admin/upload-links` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/admin/upload-links` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/admin/upload-links/{public_id}/extend` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/admin/upload-links/{public_id}/revoke` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/admin/upload-links/{public_id}/rotate` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/app/upload-screenshot` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/auth/check` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/auth/desktop/activate` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/auth/pair` | 允许 | 连接码 + 幂等绑定证明；限流；不需要既有 Bearer |
| POST | `/api/auth/refresh` | 允许 | 当前/恢复期 App 凭证 + 刷新证明；不允许网页挑战 |
| GET | `/api/bill-splits/inbox` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/bill-splits/sent` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/bill-splits/{public_id}/accept` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/bill-splits/{public_id}/cancel` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/bill-splits/{public_id}/reject` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/bootstrap/installation-owner` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/bootstrap/owner` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/bootstrap/pairing-codes` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/budget/advise` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/advisor/inputs` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/advisor/status` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/arrangements/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/budget/arrangements/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/arrangements/{month}/history` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/discretionary` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/envelopes/history/list` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budget/envelopes/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/budget/envelopes/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budgets/monthly` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| DELETE | `/api/budgets/monthly/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/budgets/monthly/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/budgets/monthly/{month}/history` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/dashboard/cards` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/dashboard/cards` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debt-bills` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debt-bills` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debt-bills/by-key/{capture_key}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debt-bills/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debt-bills/{public_id}/discard` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debt-bills/{public_id}/original` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debt-bills/{public_id}/parse` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debt-bills/{public_id}/parse-attempts/{attempt_key}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/parse-bill` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts/receivables` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts/{public_id}/activity` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/adjustments` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/forgive` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/kind` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts/{public_id}/repayment-proposals` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/repayment-proposals` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/repayment-proposals/{proposal_public_id}/reject` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/repayment-proposals/{proposal_public_id}/withdraw` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/repayment-voids` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts/{public_id}/repayments` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/repayments` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/debts/{public_id}/split-agreement` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/split-change-proposals` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/split-change-proposals/{proposal_public_id}/accept` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/split-change-proposals/{proposal_public_id}/reject` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/split-change-proposals/{proposal_public_id}/withdraw` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/debts/{public_id}/void` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/duplicates` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/exchange-rates` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/exchange-rates/conversion` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/exchange-rates/reference` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/exchange-rates/reference` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/exchange-rates/{currency_code}/{rate_date}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/categories` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/categories/preferences` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/categories/preferences` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/categories/preferences/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/categories/preferences/{public_id}/delete` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/categories/preferences/{public_id}/restore` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/confirmed` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/confirmed/batch-update` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/export.csv` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/manual` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/months` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/notification-drafts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/pending` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/tags` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/expenses/{expense_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/confirm` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/corrections` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/fact-bundle` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/funding` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/funding` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/fx` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/fx` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/image` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/items` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/expenses/{expense_id}/items` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/items/acknowledge-mismatch` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/mark-not-duplicate` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/ocr/retry` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/ocr/tasks` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/offsets` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/offsets/{offset_public_id}/corrections` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/offsets/{offset_public_id}/voids` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/original` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/original/attach` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/original/cleanup/cancel` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/original/cleanup/retry` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/original/replenish` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/original/verify` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/recognize-text` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/reject` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/repayment-draft` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/revisions` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/split-invite` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/splits` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/expenses/{expense_id}/splits` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/suggestions/{decision_public_id}/accept` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/suggestions/{decision_public_id}/reject` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/expenses/{expense_id}/thumbnail` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/expenses/{expense_id}/undo` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/exports/ledgers` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/exports/portable` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/funds/accounts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/funds/accounts/existing-debts/list` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/funds/accounts/summary/net-worth` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/funds/accounts/templates/list` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/funds/accounts/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/funds/accounts/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/activities` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/activities/void` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/credit-applications` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/credit-applications/void` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/fees` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/funds/accounts/{public_id}/installments` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/installments` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/repay` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/funds/accounts/{public_id}/repayments/void` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/goals` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/goals` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/goals/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/goals/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/goals/{public_id}/archive` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/goals/{public_id}/debt-links` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/goals/{public_id}/history` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/goals/{public_id}/integrity-review/acknowledge` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/goals/{public_id}/restore` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/goals/{public_id}/target-date` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/health` | 允许 | 匿名最小健康结果，不含安装或数据身份 |
| GET | `/api/health/installation` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/imports/csv` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/imports/csv/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/imports/csv/{public_id}/apply` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/imports/csv/{public_id}/errors.csv` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/imports/csv/{public_id}/rows` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/imports/csv/{public_id}/rows/{line_number}/review` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/income-plans` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/income-plans` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| DELETE | `/api/income-plans/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/income-plans/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/income-plans/{public_id}/history` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/income-plans/{public_id}/restore` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/insights/data-quality` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/insights/recurring-candidates` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/invitations/accept` | 允许 | 邀请 capability；提交已有会话时还需验证该会话 |
| POST | `/api/invitations/preview` | 允许 | 邀请 capability；提交已有会话时还需验证该会话 |
| GET | `/api/ledgers` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/ledgers/{ledger_id}/audit` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/ledgers/{ledger_id}/calendar` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/calendar` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/ledgers/{ledger_id}/devices` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/devices/pairing-codes` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/devices/{public_id}/delete` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/devices/{public_id}/rename` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/devices/{public_id}/revoke` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/ledgers/{ledger_id}/invitations` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/invitations` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/invitations/{public_id}/revoke` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/ledgers/{ledger_id}/members` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/members/{member_id}/disable` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/members/{member_id}/role` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/name` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/switch` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/ledgers/{ledger_id}/switch/prepare` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/maintenance/cleanup-ai-advisor-audit` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/maintenance/cleanup-devices` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/maintenance/cleanup-images` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/maintenance/cleanup-learning` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/maintenance/cleanup-orphans` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/api/maintenance/cleanup-rejected` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/api/maintenance/learning-status` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/api/merchants/aliases` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/merchants/aliases` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| DELETE | `/api/merchants/aliases/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/merchants/aliases/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/merchants/aliases/{public_id}/undo` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/merchants/catalog` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/merchants/catalog` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| DELETE | `/api/merchants/catalog/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/merchants/catalog/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/merchants/catalog/{source_public_id}/merge` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/payment-captures` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/payment-captures` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/payment-captures/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/payment-captures/{public_id}/decision` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recurring/from-candidate` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/recurring/items` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recurring/items` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/recurring/items/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/recurring/items/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recurring/items/{public_id}/archive` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/recurring/items/{public_id}/history` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/recurring/items/{public_id}/occurrences/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PUT | `/api/recurring/items/{public_id}/occurrences/{month}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recurring/items/{public_id}/pause` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recurring/items/{public_id}/restore` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recurring/items/{public_id}/resume` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/recycle-bin` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/recycle-bin/restore` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/repayment-drafts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/repayment-drafts` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/repayment-drafts/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/repayment-drafts/{public_id}/as-expense` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/repayment-drafts/{public_id}/confirm` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/repayment-drafts/{public_id}/dismiss` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/reports/overview` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/reports/overview.csv` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/rules/applications` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/applications/{public_id}/rollback` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/rules/applications/{public_id}/rollback-preview` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/apply-confirmed` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/apply-pending` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/apply-pending/preview` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/rules/categories` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/categories` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| DELETE | `/api/rules/categories/{rule_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/rules/categories/{rule_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/categories/{rule_id}/undo` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/rules/preview` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/saved-views` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/saved-views` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| DELETE | `/api/saved-views/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/saved-views/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| PATCH | `/api/saved-views/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/saved-views/{public_id}/results` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/settings/account` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/settings/account` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/settings/server` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/stats/lifestyle` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/stats/monthly` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/status/private` | 拒绝 | 私有运行信息，保留 App 鉴权，但不进公网 ingress |
| GET | `/api/system/runtime-compatibility` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/tags` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/tags` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/tags/mutations/{mutation_public_id}/undo` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/tags/{public_id}/delete` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/tags/{public_id}/merge` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/tags/{public_id}/rename` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/tasks` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| GET | `/api/tasks/{public_id}` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/tasks/{public_id}/cancel` | 允许 | App Bearer；Backend 继续执行角色、账本和设备隔离 |
| POST | `/api/upload-screenshot` | 拒绝 | 已退役上传入口；不进公网 ingress |
| GET | `/api/upload/check` | 拒绝 | 已退役上传入口；不进公网 ingress |
| GET | `/desktop/public-connectivity` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/desktop/session/revoke` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/ai-advisor` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ai-advisor/confirmation` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ai-advisor/settings` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ai-advisor/test` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/algorithm-versions` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/algorithm-versions/policy` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/algorithm-versions/withdraw` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/algorithm-versions/withdraw-feedback` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/devices` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/devices/{public_id}/delete` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/devices/{public_id}/rename` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/devices/{public_id}/revoke` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/diagnostics` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/fx` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/fx/refresh` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/fx/settings` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/learning-maintenance` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/learning-maintenance/dismiss-decision` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/learning-maintenance/original-text-evaluation` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/learning-maintenance/run` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/ledgers` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ledgers` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ledgers/{ledger_id}/archive` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/ledgers/{ledger_id}/calendar` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ledgers/{ledger_id}/calendar` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ledgers/{ledger_id}/name` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/ledgers/{ledger_id}/unarchive` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/local-models` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/originals` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/originals/inspect` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/originals/tasks/{public_id}/files/{index}` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/originals/tasks/{public_id}/{action}` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/pairing` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/pairing` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/rule-applications` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/about` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/api` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/maintenance` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/settings/maintenance` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/maintenance/preview` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/settings/maintenance/run` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/public-base-url` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/recognition` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/security` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/settings/uploads` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/settings/uploads` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/settings/{settings_group}` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/owner/upload-links` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/upload-links` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/upload-links/{public_id}/delete` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/upload-links/{public_id}/extend` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/upload-links/{public_id}/limits` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/upload-links/{public_id}/revoke` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/owner/upload-links/{public_id}/rotate` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/u/{upload_key}` | 允许 | 专用 UploadLink capability；有效期、次数、大小和 MIME 限制 |
| GET | `/web` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/auth/join` | 允许 | Web 邀请 capability 与绑定证明；表单 CSRF |
| POST | `/web/auth/join/accept` | 允许 | Web 邀请 capability 与绑定证明；表单 CSRF |
| POST | `/web/auth/join/preview` | 允许 | Web 邀请 capability 与绑定证明；表单 CSRF |
| GET | `/web/auth/ledgers` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/auth/ledgers` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/auth/local` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/web/auth/local` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/web/auth/login` | 允许 | Web 连接码与绑定证明；表单 CSRF |
| POST | `/web/auth/login` | 允许 | Web 连接码与绑定证明；表单 CSRF |
| POST | `/web/auth/logout` | 允许 | 撤销当前 Web cookie 会话；表单 CSRF；无会话时清 cookie |
| GET | `/web/auth/whoami` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/bill-splits/inbox` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/bill-splits/sent` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/bill-splits/{public_id}/accept` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/bill-splits/{public_id}/accept` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/bill-splits/{public_id}/cancel` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/bill-splits/{public_id}/reject` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/budget-advise` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/budget-advise` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/budget-advise/history` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/budget-advise/rates` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/budget-advise/rates` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/budget-advise/rates/reference` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/budget-advise/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/budgets` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/budgets/archive` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/budgets/history` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/budgets/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/categories` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/categories/preferences/{public_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/categories/uncategorized` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/categories/uncategorized/bulk-set` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/confirmed` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/confirmed/batch-update` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/currency-adoption` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/web/currency-adoption` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| POST | `/web/currency-adoption/change` | 拒绝 | 不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行 |
| GET | `/web/dashboard/cards` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/dashboard/cards/reset` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/dashboard/cards/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/data-quality` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-bills` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-bills` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-bills/by-key/{capture_key}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-bills/{public_id}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-bills/{public_id}/discard` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-bills/{public_id}/original` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-bills/{public_id}/parse` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-bills/{public_id}/parse-attempts/{attempt_key}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-goals` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-goals/new` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/{public_id}/archive` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-goals/{public_id}/links` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/{public_id}/links` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/{public_id}/restore` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/{public_id}/review/acknowledge` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/{public_id}/review/remove-voided` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debt-goals/{public_id}/target-date` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debt-goals/{public_id}/target-date` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts/new` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/rate` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts/{public_id}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/adjustments` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts/{public_id}/bill-sources/{source_id}/original` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/forgive` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/kind` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts/{public_id}/repayment-proposals` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/repayment-proposals` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/confirm` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/reject` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/repayment-proposals/{proposal_public_id}/withdraw` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/repayment-voids` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts/{public_id}/repayments` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/repayments` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/debts/{public_id}/split-agreement` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/split-agreement/preview` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/split-changes` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/split-changes/{proposal_public_id}/accept` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/split-changes/{proposal_public_id}/reject` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/split-changes/{proposal_public_id}/withdraw` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/debts/{public_id}/void` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/duplicates` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/duplicates/{expense_id}/decision` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/duplicates/{expense_id}/decision` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/duplicates/{expense_id}/keep` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/duplicates/{expense_id}/reject-current` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/duplicates/{expense_id}/reject-original` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/envelopes` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/envelopes/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/new` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/new` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/new/result` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/confirm` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/confirmation/{command_key}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/correct` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/correction-rate` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/corrections` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/funding` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/funding` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/fx` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/fx-status` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/image` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/items/acknowledge-mismatch` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/items/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/ocr/retry` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/ocr/retry` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/ocr/tasks/{public_id}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/ocr/tasks/{public_id}/cancel` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/offset-rate` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/offsets` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/offsets/{offset_public_id}/voids` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/original` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/original/attach` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/original/cleanup/cancel` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/original/cleanup/retry` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/original/health` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/original/replenish` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/original/verify` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/recognize-text` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/recognize-text` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/reject` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/split-invite` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/splits/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/thumbnail` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/expenses/{expense_id}/undo` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/expenses/{expense_id}/undo` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/export.csv` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/export/portable` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/exports` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/family` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/family/invitations` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/family/invitations/{public_id}/revoke` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/family/members/{member_id}/disable` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/family/members/{member_id}/role` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/family/members/{member_id}/transfer-owner` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/family/name` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/funds` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/funds/conversion` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/funds/save` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/goals` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/goals/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/goals/{public_id}/archive` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/goals/{public_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/goals/{public_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/goals/{public_id}/history` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/import` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/import/confirm` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/import/preview` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/import/{public_id}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/import/{public_id}/apply` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/import/{public_id}/errors.csv` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/import/{public_id}/rows/{line_number}/review` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/import/{public_id}/rows/{line_number}/review` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/income-plans` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/income-plans/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/income-plans/{public_id}/archive` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/income-plans/{public_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/income-plans/{public_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/income-plans/{public_id}/history` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/income-plans/{public_id}/restore` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/library` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/merchants` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/aliases/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/aliases/{public_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/aliases/{public_id}/toggle` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/aliases/{public_id}/undo` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/catalog/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/catalog/{public_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/catalog/{public_id}/merge` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/catalog/{public_id}/rename` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/merchants/catalog/{public_id}/toggle` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/originals` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/overview` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/payment-captures/{public_id}/decision` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/pending` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/pending/batch-reject` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/pending/batch-undo` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/pending/upload` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/receivables` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/recurring` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/confirm-candidate` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/{public_id}/archive` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/{public_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/recurring/{public_id}/history` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/recurring/{public_id}/occurrence` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/{public_id}/occurrence` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/{public_id}/pause` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/{public_id}/restore` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recurring/{public_id}/resume` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/recycle-bin` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/recycle-bin/restore` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/reference/{kind}/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/reference/{kind}/new` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/repayment-drafts` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/repayment-drafts/{public_id}` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/repayment-drafts/{public_id}/review` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/reports` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/reports/export.csv` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/review/bulk` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/rules` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/rules/applications/{public_id}/rollback` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/applications/{public_id}/rollback` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/apply-confirmed` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/apply-pending` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/create` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/{rule_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/rules/{rule_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/{rule_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/{rule_id}/toggle` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/rules/{rule_id}/undo` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/saved-views` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/saved-views` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/saved-views/{public_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/saved-views/{public_id}/open` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/saved-views/{public_id}/rename` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/search` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/settings` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/settings/account/name` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/settings/devices/pairing-codes` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/settings/devices/{public_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/settings/devices/{public_id}/rename` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/settings/devices/{public_id}/revoke` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/tags` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/tags/mutations/{mutation_public_id}/undo` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/tags/{public_id}/delete` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| GET | `/web/tags/{public_id}/edit` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/tags/{public_id}/merge` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
| POST | `/web/tags/{public_id}/rename` | 允许 | Web HttpOnly cookie；写操作 CSRF；角色与账本隔离 |
