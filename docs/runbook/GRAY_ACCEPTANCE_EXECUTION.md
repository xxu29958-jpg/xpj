# 小票夹灰度验收执行清单

本清单用于灰度发布前逐项验收，每项必须实际执行并记录结果。不写"建议验证"等不可执行项，不预填"已通过"。

gray/internal 泄漏验收口径是"普通用户 UI 不可见"：gray 版主流程和设置页不得显示服务器域名、token、Cloudflare、端口、接口名、日志或诊断脚本。它不是 APK 字符串、反编译产物或网络包级别的不可见审计；v0.3 再另开 build secrets / APK string scan 专项。

## 验收环境

- Windows 11 主机（小票夹后端运行机）
- Android 真机（灰度用户版 APK）
- iPhone（快捷指令上传）
- Cloudflare Tunnel 公网域名

---

## 1. 后端启动与健康

**验收项**：Windows 后端能正常启动，本机 health 接口返回 ok。

**执行人**：服务拥有者

**执行命令/动作**：

```bat
cd /d E:\projects\xiaopiaojia\backend
run.bat
```

在另一个终端执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

**预期结果**：

```json
{"status":"ok"}
```

**失败处理**：

- 如果端口被占用，运行 `scripts\stop_backend.ps1` 后再启动。
- 如果 `.venv` 缺失，先运行 `setup.bat`。
- 如果返回非 JSON 或超时，检查 `backend\logs\ticketbox-backend-*.out.log` 中的启动异常。

**是否阻断灰度**：是。后端不启动，整条链路不可用。

**证据路径**：`backend\logs\ticketbox-backend-*.out.log` + 终端截图

**状态**：

---

## 2. 后端代码检查与测试

**验收项**：后端代码能通过编译检查、lint 和冒烟测试。

**执行人**：服务拥有者

**执行命令/动作**：

```bat
cd /d E:\projects\xiaopiaojia\backend
.venv\Scripts\python.exe -m compileall app scripts tests
.venv\Scripts\ruff.exe check app scripts tests
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\smoke_test.py
```

**预期结果**：

- `compileall` 无 SyntaxError。
- `ruff check` 无错误。
- `pytest` 全部通过或仅有已知跳过项。
- `smoke_test.py` 连续输出 `OK ...` 检查项，进程退出码为 0。

**失败处理**：

- 若 pytest 失败，查看具体失败用例，确认不是环境配置问题后再决定是否放行。
- 若 smoke_test 失败，检查后端是否已启动、`.env` 是否存在。

**是否阻断灰度**：是。冒烟失败说明基础接口异常。

**证据路径**：终端输出截图

**状态**：

---

## 3. Cloudflare Tunnel 公网可达

**验收项**：公网域名能访问本机后端，health 和 auth 检查通过。

**执行人**：服务拥有者

**执行命令/动作**：

```powershell
cd E:\projects\xiaopiaojia
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
$env:TICKETBOX_UPLOAD_LINK="/u/<upload_key>?tz=Asia/Shanghai"
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.你的域名.com
```

> v0.3 以后 `check_cloudflare_endpoint.ps1` 不再从 `backend\.env` 读取旧 `APP_TOKEN`/`UPLOAD_TOKEN`。请通过 `-SessionToken` / `-UploadLink` 参数，或 `TICKETBOX_SESSION_TOKEN` / `TICKETBOX_UPLOAD_LINK` 环境变量传入当前有效凭证。

**预期结果**：

- `/api/health` 返回 ok。
- `/api/auth/check` 返回 session token 有效。
- UploadLink 上传测试成功。

**失败处理**：

- 若 health 不通，检查 Windows 是否睡眠、后端是否运行、cloudflared 是否运行。
- 若 auth 失败，检查设备 session token 是否有效或是否被撤销。
- 若上传失败，检查 UploadLink URL 是否正确。

**是否阻断灰度**：是。公网不通，手机离开 Wi-Fi 后无法使用。

**证据路径**：终端输出截图

**状态**：

---

## 4. 出门前保障检查

**验收项**：一键保障脚本能启动后端/Tunnel 并通过公网检查。

**执行人**：服务拥有者

**执行命令/动作**：

```powershell
cd E:\projects\xiaopiaojia
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_ticketbox_runtime.ps1 `
  -ServerUrl https://api.你的域名.com
```

**预期结果**：

- 后端已启动或自动启动。
- cloudflared 已启动或自动启动。
- 公网 health 检查通过。

**失败处理**：

- 若脚本无法启动后端，手动运行 `run.bat` 排查。
- 若 Tunnel 无法启动，检查 `cloudflared` 服务或计划任务状态。

**是否阻断灰度**：否。但这是日常可靠性保障，首次灰度建议执行。

**证据路径**：终端输出截图

**状态**：

---

## 5. iPhone 快捷指令上传

**验收项**：iPhone 通过快捷指令上传截图，后端创建 pending 账单。

**执行人**：灰度用户 / 服务拥有者

**执行命令/动作**：

1. 在 iPhone 上打开一张账单截图。
2. 点击分享，选择"上传到小票夹"。
3. 等待快捷指令完成，显示"已上传到小票夹"。

快捷指令配置预检（首次配置时）：

```text
URL: https://api.你的域名.com/u/<upload_key>?tz=Asia/Shanghai
方法: POST
请求头:
  User-Agent: TicketBox/1.0 iOS-Shortcut
请求正文: 文件（转换后的图像）
```

> **注意**：v0.3 不再使用 `Upload-Token` header。快捷指令 URL 必须是完整的 UploadLink，包含 `/u/<upload_key>`。

**预期结果**：

- 快捷指令显示"已上传到小票夹"。
- Android 待确认页或数据库中新增一条 `status=pending` 记录。
- 后端默认关闭 Uvicorn access log，不应为了查看 `/u/<upload_key>` 路径打开访问日志。

**失败处理**：

- 若提示网络中断，先用 Safari 打开 `https://api.你的域名.com/api/health`。
- 若返回 `legacy_auth_removed`，说明快捷指令仍使用旧版 `Upload-Token` 或 `/api/upload-screenshot`，需要更新为完整 UploadLink URL。
- 若返回 `invalid_token`，检查 UploadLink URL 中的 `upload_key` 是否正确。
- 若返回 `invalid_request`，检查请求正文是否为 `文件` 模式，不要选 `表单`。
- 若返回 `unsupported_file_type`，快捷指令增加"转换图像"为 JPEG/PNG 步骤。
- 若返回 `file_too_large`，单图超过 10MB，先压缩再上传。

**是否阻断灰度**：是。iPhone 上传是灰度核心闭环入口。

**证据路径**：iPhone 快捷指令完成截图 + 后端日志截图

**状态**：

---

## 5A. 真实图片样本上传

**验收项**：真实截图和伪造样本的上传结果符合安全预期。

**执行人**：服务拥有者 / 灰度用户

**执行命令/动作**：

按下列样本分别走 iPhone 快捷指令或 Android 上传入口，记录结果：

| 样本 | 入口 | 预期结果 |
| --- | --- | --- |
| iPhone JPEG 账单截图 | iPhone 快捷指令 | 创建 pending，缩略图可见 |
| iPhone PNG 账单截图 | iPhone 快捷指令 | 创建 pending，缩略图可见 |
| iPhone HEIC 原图 | iPhone 快捷指令 | 创建 pending，后端完成 HEIC 解码校验，并尽量生成 JPEG 缩略图 |
| Android JPEG 截图 | Android 上传 | 创建 pending，待确认页可见 |
| Android PNG 截图 | Android 上传 | 创建 pending，待确认页可见 |
| 微信支付截图 | iPhone 或 Android | 创建 pending，OCR 只填草稿，不自动入账 |
| 支付宝账单截图 | iPhone 或 Android | 创建 pending，OCR 只填草稿，不自动入账 |
| 长截图 | iPhone 或 Android | 可上传或被大小限制拒绝；不得白屏或生成 confirmed |
| 接近 10MB 的真实图片 | iPhone 或 Android | 小于限制则 pending，超过限制返回 `file_too_large` |
| fake JPEG | curl / 测试脚本 | 返回 `unsupported_file_type`，不残留文件 |
| fake HEIC | curl / 测试脚本 | 返回 `unsupported_file_type`，不残留文件 |

**预期结果**：

- 所有成功上传都只创建 pending。
- 所有伪造图片都被拒绝。
- API 不返回 Windows 本机真实路径。
- 上传失败不残留文件。

**是否阻断灰度**：是。真实图片样本不过，不进入当前版本真机验收。

**证据路径**：样本清单截图 + Android 待确认页截图 + 后端测试输出

**状态**：

---

## 6. Android 构建与安装

**验收项**：灰度用户版 APK 能正常构建并安装到真机。

**执行人**：服务拥有者

**执行命令/动作**：

如果使用 PR artifact 作为当前版本真机验收包，先执行 artifact 门禁：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_rc_artifacts.ps1 `
  -RunId <run_id> `
  -ExpectedCommit <commit_sha>
```

脚本通过后，使用 `artifacts\rc-gate\<run-id>\<release-candidate>-handoff-checklist.md` 作为发包清单。
未生成 manifest 和 handoff checklist 的 artifact，不得称为当前版本验收包。

```powershell
cd E:\projects\xiaopiaojia\android
$env:JAVA_HOME="$env:LOCALAPPDATA\Programs\Kimi\runtime"
$env:ANDROID_HOME=(Resolve-Path "..\.toolchains\android-sdk").Path
$env:PATH="$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"
.\gradlew.bat --no-daemon :app:assembleGrayDebug
```

安装到真机：

```powershell
cd E:\projects\xiaopiaojia
$adb = "$env:ANDROID_HOME\platform-tools\adb.exe"
& $adb devices
& $adb -s 设备序列号 install -r android\app\build\outputs\apk\gray\debug\app-gray-debug.apk
```

**预期结果**：

- PR artifact 门禁脚本退出码为 0。
- gray/internal APK 的 package、versionName、versionCode、SHA256 已记录。
- 发包清单写明绑定码发放对象和不得发出的凭证。
- `assembleGrayDebug` BUILD SUCCESSFUL。
- `adb install` 返回 Success。
- 真机桌面出现"小票夹"图标。

**失败处理**：

- 若编译失败，查看错误日志，先 `clean` 再试。
- 若 adb 找不到设备，检查 USB 调试、数据线、驱动。
- 若安装失败，检查是否已存在同名包，用 `-r` 覆盖安装。

**是否阻断灰度**：是。没有 APK，灰度用户无法使用。

**证据路径**：编译终端截图 + adb install 输出截图 + 真机桌面截图

**状态**：

---

## 7. Android 绑定账本

**验收项**：灰度用户首次打开 App 能成功绑定服务器。

**执行人**：灰度用户

**执行命令/动作**：

1. 真机打开"小票夹"。
2. 输入账本地址：`https://api.你的域名.com`。
3. 输入服务拥有者提供的 8 位绑定码（Pairing Code）。
4. 点击"绑定账本"。

> **注意**：v0.3 不再使用旧版 `APP_TOKEN`。Android 绑定需要服务器地址 + 8 位数字绑定码。

**预期结果**：

- 绑定成功，进入 App 主界面（底部导航：待确认 / 账本 / 统计 / 设置）。
- 设置页显示"已连接"。
- Android 在 `POST /api/auth/pair` 成功后先保存 session 和身份，再恢复 confirmed。
- 如果恢复失败，仍进入 App，并提示"已绑定，但历史账本恢复失败，可稍后在账本页更新。"；用户可进入账本页手动更新。
- Room 本地 confirmed 缓存通过 `syncConfirmed()` 重建。

**失败处理**：

- 若提示"绑定没成功，请检查账本地址和绑定码"：
  - 确认地址是 `https://` 开头，不是 `http://`。
  - 确认不是 `localhost` 或 `127.0.0.1`。
  - 确认输入的是 8 位数字绑定码，不是旧版 `APP_TOKEN`。
  - 确认绑定码未过期（默认 15 分钟）且未被使用过。
  - 用 Safari/浏览器打开 `https://api.你的域名.com/api/health` 确认公网可达。
- 若返回 `legacy_auth_removed`，说明后端已升级 v0.3，必须使用新绑定码。

**是否阻断灰度**：是。绑定失败，用户无法进入 App。

**证据路径**：真机绑定成功界面截图

**状态**：

---

## 7.1 Android 卸载重装恢复 E2E

**验收项**：卸载重装后重新绑定同一账本，能恢复 confirmed 到 Room，断网后仍可查看。

**执行人**：服务拥有者

**执行命令/动作**：

1. 后端确认至少有 1 笔 confirmed 账单。
2. 生成新的 Pairing Code。
3. 卸载 Android App，重新安装当前版本 gray 包。
4. 首次打开 App，输入服务器地址和 Pairing Code。
5. 绑定成功后进入"账本"页，确认历史 confirmed 账单出现。
6. 停止本机后端或让手机断网。
7. 强停并重新打开 App，再进入"账本"页。

**预期结果**：

- 绑定成功后设置页显示账号、账本、设备和角色。
- 账本页出现卸载前已有的 confirmed 账单。
- 断网或后端停止后，账本页仍从 Room 显示这些账单。
- 如果绑定后首次恢复失败，App 仍保持已绑定，用户可在账本页点击更新后恢复。

**失败处理**：

- 若绑定码已使用，需要重新生成 Pairing Code。
- 若账本页为空，先联网点击"更新账本"，再断网复测。
- 若绑定成功后 App 回到未绑定页，说明 session 保存顺序有回归，阻断 alpha。

**是否阻断灰度**：是。卸载重装恢复不过，不进入 v0.3-alpha 真机扩大测试。

**证据路径**：卸载重装绑定截图 + 账本页在线截图 + 断网账本页截图

**状态**：

---

## 8. 待确认账单拉取与编辑

**验收项**：iPhone 上传后，Android 待确认页能拉取到 pending 账单，编辑页能查看截图、补全金额并确认入账。

**执行人**：灰度用户

**执行命令/动作**：

1. 确保 iPhone 已上传至少一张截图（验收项 5）。
2. Android 打开"待确认"页，下拉刷新。
3. 点击账单卡片进入编辑页。
4. 确认截图缩略图可见，点击"看原图"能查看大图。
5. 填写金额、商家、分类、备注和消费时间。
6. 点击"确认入账"。

**预期结果**：

- 待确认页显示上传的截图账单，状态为"待确认"。
- 编辑页截图预览正常。
- 确认后该账单从待确认页消失。
- 后端日志出现 `POST /api/expenses/{id}/confirm` 200 记录。

**失败处理**：

- 若待确认页为空，检查 iPhone 上传是否成功，检查网络，下拉刷新。
- 若截图无法预览，检查网络或返回待确认页重试。
- 若确认入账失败，检查金额是否已填写，检查网络连接。

**是否阻断灰度**：是。确认入账是核心闭环。

**证据路径**：真机待确认页截图 + 编辑页截图 + 确认后账本页截图

**状态**：

---

## 9. 账本页与统计页

**验收项**：已确认账单在账本页可见，统计页数据正确更新。

**执行人**：灰度用户

**执行命令/动作**：

1. 进入"账本"页，确认刚入账的账单出现在列表中。
2. 点击月份筛选，切换月份，确认列表刷新。
3. 进入"统计"页，查看本月总支出、分类占比、最近 7 天趋势。

**预期结果**：

- 账本页显示已确认账单，包含金额、商家、分类、时间。
- 统计页本月总支出包含刚确认的账单金额。
- 分类占比和最近 7 天趋势数据正常显示。

**失败处理**：

- 若账本页为空，检查是否已确认入账，检查月份筛选是否为当前月。
- 若统计页数据不对，下拉刷新或进入设置页点击"更新账本"。

**是否阻断灰度**：否。不影响基础闭环，但影响体验，建议修复后再放量。

**证据路径**：真机账本页截图 + 统计页截图

**状态**：

---

## 10. 表格导出

**验收项**：账本页能导出已确认账单为表格文件。

**执行人**：灰度用户

**执行命令/动作**：

1. 进入"账本"页，确认有已确认账单。
2. 点击"筛选与更新"底部弹窗中的"导出表格"。
3. 选择保存位置，完成导出。

**预期结果**：

- 系统文件选择器弹出。
- 保存后的文件能用 Excel/WPS 打开，内容为 CSV 格式，包含金额、商家、分类、时间、备注。
- 文件名为 `ticketbox-expenses-YYYY-MM.csv`。

**失败处理**：

- 若导出按钮禁用，确认账本页有已确认账单。
- 若导出失败，检查网络连接，检查存储权限。

**是否阻断灰度**：否。导出是增值功能，不影响核心闭环。

**证据路径**：导出文件截图 + Excel 打开截图

**状态**：

---

## 11. 断网账本（本地缓存）

**验收项**：断开网络后，账本页仍能查看已缓存的已确认账单。

**执行人**：灰度用户

**执行命令/动作**：

1. 确认已有至少一笔已确认账单（验收项 8）。
2. 手机开启飞行模式或关闭 Wi-Fi 和蜂窝数据。
3. 进入"账本"页。
4. 尝试切换月份，查看列表。

**预期结果**：

- 账本页仍显示已确认账单列表。
- 金额、商家、分类、时间正常可读。
- 状态提示显示"离线可查看"或类似本地缓存提示。

**失败处理**：

- 若断网后账本为空，说明本地 Room 缓存未写入，检查之前是否成功同步过账本。
- 重新连接网络后，进入设置页点击"更新账本"，再断开网络测试。

**是否阻断灰度**：否。但离线查看是灰度版承诺的可用性保障，建议通过。

**证据路径**：真机断网状态截图 + 账本页截图

**状态**：

---

## 12. 备份与恢复

**验收项**：Windows 计划任务能自动备份 SQLite 数据库，恢复脚本可用。

**执行人**：服务拥有者

**执行命令/动作**：

检查备份任务是否存在：

```powershell
Get-ScheduledTask -TaskName TicketboxBackup
```

手动触发一次备份（可选）：

```powershell
# 查看已有备份
Get-ChildItem E:\projects\xiaopiaojia\backend\backups\*.db -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3
```

恢复测试（在测试环境或非生产数据库上执行）：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\restore_ticketbox_db.ps1 `
  -BackupPath "E:\projects\xiaopiaojia\backend\backups\ticketbox-YYYYmmdd-HHMMSS.db"
```

> **注意**：v0.3 只会在发现 pre-v0.3 数据库结构时创建 `backups\ticketbox-pre-v0.3-YYYYMMDD-HHMMSS.db`。身份表迁移完成后，后续重启不会重复生成新的 pre-v0.3 备份。回滚到 v0.2 时使用首次迁移前的备份。

**预期结果**：

- `TicketboxBackup` 计划任务状态为 Ready 或 Running。
- `backend\backups\` 目录下有 `.db` 备份文件。
- 恢复脚本执行成功，数据库文件被替换，后端重启后数据正常。

**失败处理**：

- 若备份任务不存在，运行 `scripts\install_windows_tasks.ps1` 创建。
- 若恢复失败，检查备份文件路径是否正确，检查后端是否已停止。

**是否阻断灰度**：否。备份是运维保障，不直接影响用户功能，但首次灰度前建议确认备份机制正常。

**证据路径**：计划任务状态截图 + backups 目录文件列表截图

**状态**：

---

## 13. Android lint 与单元测试

**验收项**：灰度版通过 Android lint 和单元测试。

**执行人**：服务拥有者

**执行命令/动作**：

```powershell
cd E:\projects\xiaopiaojia\android
$env:JAVA_HOME="$env:LOCALAPPDATA\Programs\Kimi\runtime"
$env:ANDROID_HOME=(Resolve-Path "..\.toolchains\android-sdk").Path
$env:PATH="$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:lintGrayDebug
```

**预期结果**：

- `testGrayDebugUnitTest` 全部通过。
- `lintGrayDebug` BUILD SUCCESSFUL，无新增严重警告。

**失败处理**：

- 若单元测试失败，查看具体失败用例，修复后再验收。
- 若 lint 有新增严重警告，优先修复安全问题（如硬编码密钥、权限滥用）。

**是否阻断灰度**：是。lint 失败或测试失败说明构建质量不达标。

**证据路径**：终端输出截图

**状态**：

---

## 14. 设置页安全与隐私

**验收项**：灰度用户设置页不暴露开发诊断入口、不显示服务器域名和 Token。

**执行人**：灰度用户

**执行命令/动作**：

1. 打开"设置"页。
2. 逐项检查可见内容。
3. 确认没有"运行诊断/运行检测"、"刷新服务/刷新设置"、"绑定地址/连接地址"、"服务器域名"等内部入口。

**预期结果**：

- 设置页可见：当前账本、连接状态、最近上传、最近更新、存储状态、外观、分类规则、数据与导出、安全与隐私、关于。
- 不可见：服务器域名、Cloudflare、端口、接口名、诊断脚本、日志。
- "账本连接"页只显示"检查连接"和"更新账本"按钮，没有"运行检测"按钮。

**失败处理**：

- 若看到内部诊断入口，检查安装的是否为 `grayDebug` 包（包名 `com.ticketbox`），不是 `internalDebug`（包名 `com.ticketbox.internal`）。

**是否阻断灰度**：是。gray 版暴露内部入口属于严重问题。

**证据路径**：真机设置页截图

**状态**：

---

## 验收汇总表

| 序号 | 验收项 | 是否阻断 | 执行人 | 状态 | 证据 |
|:---:|:---|:---:|:---|:---:|:---|
| 1 | 后端启动与健康 | 是 | 服务拥有者 | | |
| 2 | 后端代码检查与测试 | 是 | 服务拥有者 | | |
| 3 | Cloudflare Tunnel 公网可达 | 是 | 服务拥有者 | | |
| 4 | 出门前保障检查 | 否 | 服务拥有者 | | |
| 5 | iPhone 快捷指令上传 | 是 | 灰度用户 | | |
| 5A | 真实图片样本上传 | 是 | 服务拥有者 / 灰度用户 | | |
| 6 | Android 构建与安装 | 是 | 服务拥有者 | | |
| 7 | Android 绑定账本 | 是 | 灰度用户 | | |
| 8 | 待确认账单拉取与编辑 | 是 | 灰度用户 | | |
| 9 | 账本页与统计页 | 否 | 灰度用户 | | |
| 10 | 表格导出 | 否 | 灰度用户 | | |
| 11 | 断网账本（本地缓存） | 否 | 灰度用户 | | |
| 12 | 备份与恢复 | 否 | 服务拥有者 | | |
| 13 | Android lint 与单元测试 | 是 | 服务拥有者 | | |
| 14 | 设置页安全与隐私 | 是 | 灰度用户 | | |

---

## 灰度放行标准

1. 所有"阻断"项必须标记为通过。
2. 非阻断项允许记录已知问题，但需在灰度说明中告知用户。
3. 未实际执行的项不得预填"通过"。
4. 所有证据截图按日期归档，命名格式：`YYYYMMDD_序号_简要描述.png`。

## v0.3.2 自用稳定版补充说明

v0.3.2 self-use stable candidate 的自用门禁不替代本灰度清单，二者互补：

- 本清单关注"灰度发给他人时不能泄漏服务器/凭证/调试入口"。
- 自用清单（已归入 git 历史）关注"我自己单机能稳定使用"，包含 Owner Console UX、UploadLink 安全、Android 绑定恢复、飞行模式离线可读等。
- 本轮 Owner Console UX hotfix（`upload_links.html` 双重 `?tz=`、`devices.html`/`pairing.html` 时间戳、表头 nowrap）已并入 `v0.3.2-selfuse-stabilization` 分支。
