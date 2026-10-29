# RC 接受记录 · 2026-10-30

Owner 已明确裁决 **RC acceptance has passed**。本记录将该裁决与已完成的非苹果整包验收对应，保留原候选、环境和平台边界。后续主线改动不自动获得该二进制资格；本记录不创建 tag 或 release。

## 已接受的候选

2026-10-29 的整包资格档案中，`candidate.json`、`qualification-completion.json` 和 `qualification-report.md` 对应同一候选。2026-10-30 重新读取这些记录，核对 Git tree，并实际重新计算 Setup、构建来源、发行清单、实测 APK 和 completion 所列证据的 SHA-256，全部与冻结记录一致。

| 主体 | 精确身份 |
| --- | --- |
| Source | `c67594104ebd3f2a9be4ddf0adac9f65fca75af7` |
| Tree | `8aaf4b2f302dcfef7d410e0507e42cb47660a2b7` |
| Windows Setup 1.2.0 | `34677f3c7b82301fb29f9e0a75b88e88f956cddb154912f7f5da06c1409f4c31` |
| BUILD_PROVENANCE | `ad913d99da66a99a25bbd5416cc7df8c86d69cd5257f8450af29d52cbb98d722` |
| Release manifest | `cb4d02a6292a7978a5183f5894596468396acfc064d7813c42037fc236d6bd84` |
| 实测 Android grayRelease 1.2.0 / 10200000 | `d702bfef52da9e21254b9dbfc229996a9eb124fa52a1ac0797d3574c88536297` |
| APK 签名证书 | `f6a477c823f1c1fccdc2e96b1a50dc7e57156f39d6c470cc3ce07af78568e075` |
| Schema | `20261028_0001` |

完整私有档案及此次 `cx1-acceptance-verification-r1.json` 由唯一当前交接定位；原件、账务正文、凭据和设备数据不进入仓库。

## 已执行的范围

原验收实际覆盖 Windows Setup、普通 Desktop、Web、Owner 和 Android 的四条连续旅程：安装接入、收件到账务、家庭财务连续性、故障后继续使用。原件、财务事实、成员关系和未提交意图的后置条件均已核对。适用的离线与丢回执恢复、会话轮换、冲突隔离、便携导出、完整冷备、同候选 R1 恢复和正常重启后的新旧业务回读均已执行通过。

环境为专用 Windows 11 Pro VM（2 CPU / 4 GiB、PG 17.11-1、无外网网卡）、Android API 36 模拟器，以及仅本机 QA TLS 到实际 VM 后端的传输。这不是实体手机、真实公网 Tunnel 或自动登录的证明。此次只重新核验来源和证据完整性，没有冒充重新执行这些历史旅程。

## 保留边界

- iPhone、iPad 由 Owner 延期，状态仍为 deferred / unverified；延期不否定上述已接受范围。
- R2 异机恢复、U1 升级失败恢复、C1 独立加密副本保持 HOLD。既有有界 R1 的原证据继续有效。
- 不据此宣称所有平台 `INTERNAL_BETA_READY`，不提升发行权限。
- 后续 OCR 专项的 `0286620cd8df6da999d54f3122f9d37067b660dd` 及其 Setup/APK 有独立的专项资格；它们不是本表中的 RC 接受物。#718、#719 的前端主线变化也不能替换本表中的二进制身份。
- Post-RC 的 OCR 生命周期、合格原文反馈消费、泛化评估及 Web 票据创建借还仍按当前授权继续。它们的未完成状态不追溯改写此次 RC 接受裁决。

原失败、重试、阶段 pending 状态和历史报告保留。当前状态由本记录和后续实际交付更新；历史 `ready=false` 或“RC 尚未退出”只代表当时的候选与范围。
