# 0006 Windows PowerShell 脚本使用 UTF-8 with BOM

## 决策

所有 `.ps1` 使用 UTF-8 with BOM 保存。`backend\.env` 使用 UTF-8 without BOM 保存。读取中文文本时，Windows PowerShell 5.1 必须显式使用 `-Encoding UTF8`。

## 原因

小票夹后端要求 Windows 11 本机运行，并且脚本里有中文输出。Windows PowerShell 5.1 读取无 BOM 的 UTF-8 脚本时，可能按系统 ANSI 代码页解释，导致中文字符串乱码，严重时会破坏脚本解析。

Microsoft Learn `about_Character_Encoding` 说明：如果脚本包含非 ASCII 字符并需要在 Windows PowerShell 中运行，应保存为 UTF-8 with BOM。

## 影响

- 新增或修改 `.ps1` 后，需要确认 Windows PowerShell 5.1 能直接运行。
- `.env` 不能使用 BOM，否则第一行配置名可能被 Python 读取成带 BOM 的 key。
- 用 PowerShell 查看 Markdown、README、Kotlin、Python、YAML 等中文文本时，必须使用 `Get-Content -Encoding UTF8`。
- CI 运行 `scripts\check_text_encoding.ps1`，检查文本文件是合法 UTF-8，并阻止常见 UTF-8/ANSI 误读后写回的乱码片段。
- 不用 WSL、Docker 或 Linux shell 作为脚本运行前提。
- `.bat` 入口继续使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...`。

## 验收

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\setup_backend.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```

必须能直接运行，不得依赖用户先修改系统编码或 PowerShell profile。

## 参考

- https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_character_encoding
