# 灰度版验收清单

日期：2026-05-05

## 1. 用户端到端验收

必须跑通：

- iPhone 快捷指令上传真实账单。
- 后端 pending 增加。
- Android 待确认出现。
- Android 编辑金额、商家、分类、备注。
- Android 确认入账。
- 账本页出现该账单。
- 统计页金额变化。
- Android 选择图片上传。
- Android 上传后待确认出现。
- 蜂窝网络访问 `api.zen70.cn`。
- 离开电脑局域网后仍能访问。

## 2. 多租户验收

必须验证：

- `tester_1` 看不到 `owner` 的 pending。
- `tester_1` 看不到 `owner` 的 confirmed。
- `tester_1` 无法下载 `owner` 的 image。
- `tester_1` 无法下载 `owner` 的 thumbnail。
- `tester_1` 统计不包含 `owner` 数据。
- `tester_1` CSV 不包含 `owner` 数据。
- `tester_1` 分类规则不影响 `owner`。
- 重复检测不跨租户。
- iOS upload_token 进入正确租户。
- Android app_token 上传到正确租户。

## 3. Android UI 验收

必须满足：

- 普通用户打开像记账 App。
- 普通用户看不到 token。
- 普通用户看不到接口名。
- 普通用户看不到服务器域名。
- 普通用户看不到 Cloudflare、端口、日志、诊断脚本。
- 用户知道截图上传后要手动确认。
- OCR 只是识别建议，不会自动入账。
- Android 有上传截图入口。
- 设置页只显示账本状态、同步状态、数据安全和外观。
- 清除本地数据二次确认。
- 清除绑定二次确认。
- `gray` 版不显示内部诊断。
- `internal` 版可以显示内部工具和连接诊断。

## 4. OCR 验收

样本来源：

- 建行
- 美团
- 京东
- 微信支付
- 支付宝
- 滴滴
- 饿了么
- 淘宝
- OpenAI
- Steam

必须验证：

- 能提取金额草稿。
- 能提取商家草稿。
- 能提取消费时间草稿。
- 能给出分类建议。
- 保存 `raw_text`。
- 保存 `confidence`。
- 不自动确认入账。
- 低置信度提示用户核对。

## 5. Release 验收

必须验证：

- release APK 能构建。
- release APK 能安装。
- release 不显示开发诊断入口。
- release 不打印 token。
- release 不展示接口名。
- release 不展示服务器域名。

## 6. Windows 运维验收

服务拥有者在 Windows 上运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```

摘要应包含：

- 本地服务是否正常。
- 外网访问是否正常。
- Cloudflare Tunnel 是否在线。
- 最近上传时间。
- 待确认数量。
- 已入账数量。
- 数据库大小。
- 图片占用。
- 租户数量。
- 默认租户。

高级模式才显示：

- 端口。
- URL。
- HTTP 状态码。
- cloudflared 进程。
- scheduled task 名称。
- 日志尾部。

高级模式命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Advanced
```

## 7. 自动化验证

后端：

```powershell
cd backend
.venv\Scripts\python.exe -m compileall app scripts tests
.venv\Scripts\ruff.exe check app scripts tests
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\smoke_test.py
```

Android：

```powershell
cd android
.\gradlew.bat --no-daemon :app:assembleGrayDebug
.\gradlew.bat --no-daemon :app:assembleInternalDebug
```

项目级：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```
