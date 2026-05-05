# Android 状态流规范

本文件是兼容入口。完整状态流规范见 [ANDROID_STATE_FLOWS.md](ANDROID_STATE_FLOWS.md)。

核心边界：

- `pending` 是截图上传后产生的待确认账单。
- OCR retry 只能更新草稿字段，不得自动入账。
- duplicate 只能提示，不得自动拒绝或删除。
- `confirmed` 代表用户手动确认后的正式入账。
- `rejected` 代表用户明确忽略待确认账单。

