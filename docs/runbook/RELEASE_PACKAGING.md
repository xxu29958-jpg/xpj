# Android Release 产物来源与本机签名

更新：2026-10-02。当前 Goal 与 Gmail Rev3.2 优先。本文只管理 APK 的构建、来源和签名，不能据此宣布 Internal Beta RC。

## 当前范围

目标是取得已经通过独立 main 门禁的云端 Release 原包，并在 Owner 本机使用持久发布密钥签名。CI 继续承担 Gradle 重构建；本机只下载、校验与签名。业务事实、应用身份、Android 运行代码、Windows 生命周期及既定 HOLD 不变。

原验收脚本混合了本地 Gitea、全仓重测、公网测试写入、本地 Release 重构建和随后的 Debug 真机安装，不能证明最终 Release 包。该编排已从 `accept_gray_release.ps1` 退役。已有诊断、上传业务旅程和开发安装工具分别保留；不能用它们代替 exact Release 演练。

## 云端构建

现有 `Android APK release` job 继续编译 `grayRelease` 与 `internalRelease`，同次读取 Gradle 实际 Build Tools 版本。构建后保存 `ticketbox-android-release-inputs-attempt-N`：

- 两个未签名 APK；
- `release-inputs.json`，记录 checkout/source/tree、repository/run/attempt、干净状态、实际 AGP 包身份和版本、APK 大小/摘要、编译服务地址、JDK/Gradle/依赖目录/Build Tools 身份。

PR artifact 仅供源资格检查。可签名的正式输入必须来自当前干净 checkout 对应的 main push；该 commit 的 CI、CodeQL、实际 Connected 均须成功。产物保留 30 天，过期须重新取得有资格的构建，不用本地重构建补称同一包。

## 持久密钥与签名

使用四个既有环境变量：`TICKETBOX_KEYSTORE_PATH`、`TICKETBOX_KEY_ALIAS`、`TICKETBOX_KEYSTORE_PASSWORD`、`TICKETBOX_KEY_PASSWORD`。密钥与密码不进 Git、CI 或回执；密码通过环境传给签名工具。预先保管并明确指定该持久密钥的公钥证书 SHA-256，不接受自动生成临时密钥或跳过来源核准。

在对应 main commit 的干净 checkout 中执行，参数中的工具路径与输出目录由本机明确提供：

```powershell
.\scripts\accept_gray_release.ps1 `
  -GitHubRunId <已通过的主干CI运行编号> `
  -OutputDirectory <新的私有产物目录> `
  -PythonPath <Python3.11可执行文件> `
  -JavaPath <JDK的java可执行文件> `
  -BuildToolsDirectory <AndroidSDK的build-tools版本目录> `
  -CertificateSha256 <持久Release证书的64位小写SHA256> `
  -ServerUrl <该release-profile的编译服务地址>
```

默认是普通用户的 `gray`，Owner 联调版本显式指定 `-Flavor internal`。`grayRelease` 不显示开发诊断入口，`internalRelease` 保留内部工具。版本号和应用 ID 仍由原 Gradle flavor/buildType 定义。

收集器通过已登录的 `gh` 读取 GitHub，核对独立主干门禁、artifact 所属运行和服务器给出的 ZIP 摘要，再校验 APK/manifest/commit/tree/服务地址。只接受预定文件，输出目录必须新建，失败不覆盖此前产物。

随后检查对齐，用本机密钥签名，由 `apksigner verify` 核对签名及指定证书，并比较签名前后全部非签名 ZIP 内容。`signed-artifact.json` 记录最终 APK SHA-256、证书、原 APK/manifest/ZIP 身份、签名工具摘要与资格运行；它明确标记 `artifact-only`。原包与失败残件保留供查明，不能当成功包使用。参考 [Android apksigner](https://developer.android.com/tools/apksigner) 与 [GitHub artifact API](https://docs.github.com/en/rest/actions/artifacts)。

## 产品与 RC 边界

签名完成不安装手机、不写公网账本、不重新配对、不创建发布标签，也不宣称 RC ready。后续必须将该 exact APK 与 exact Setup、Backend/Manager manifests、schema、工具链、release profile、HOLD 一起冻结，并完成阶段合同所需的实际整包演练。Debug APK、组件测试及同源源码通过不能替代最终 Release 运行。

`scripts/build_release_apk.ps1` 保留为显式开发构建工具，其本地 manifest 不进入本收集器。当前 Goal 禁止用本机 Android 重构建替代云端产物；旧 `UseTemporaryKeystore`、`SkipCiBinding`、Gitea 参数及自动 Debug 安装路径已退役。

交付时，普通用户只取得 gray APK、服务地址和其一次性配对码；iPhone 采集者只取得分配给自己的 UploadLink。internal APK、管理凭据由服务拥有者保管。密钥、密码、后端配置、会话令牌及含凭证的日志或截图不进入公开产物。

## 本次证据

旧主干 `0f1ab283` 的 CI `36916612970`、CodeQL 和三个实际 Connected 均已通过，但实际 artifact 列表仅有两个 Debug APK；收集器在原运行上明确拒绝“未保留 Release 输入”。本机六项窄验证覆盖生产者/消费者字节绑定、异源/失败/PR 资格拒绝，以及签名元数据与应用载荷的区分；不把合成 ZIP 当作可安装 APK。最终源的真实云端 Release 产物、独立 main 及批准的持久证书签名仍待核准。
