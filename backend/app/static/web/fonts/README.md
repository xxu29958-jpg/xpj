# Web fonts

`/web` 桌面账本（v0.10）使用本地自托管 webfont。Android 与 `/owner` 仍走系统中文字体栈，与本目录无关。

## 字体清单

| 字体 | 用途 | 权重 |
|---|---|---|
| Noto Sans SC | 中文正文与界面 | 400 / 500 / 700 / 900 |
| Newsreader | 期刊感大标题衬线（仅拉丁字符） | 400 / 500 / 400 italic |
| Inter | tabular 数字、英文标签 | 400 / 500 / 600 |

## 下载

```powershell
pwsh scripts/download-fonts.ps1
```

脚本调 Google Fonts CSS API 获取最新 woff2 子集，存到本目录。文件名规范化为 `Family-Weight[Italic].woff2`。Noto Sans SC 按 unicode-range 切片，脚本只保留桌面账本当前引用的中文主子集文件；缺失字形由系统中文字体栈兜底。

## 设计决策依据

设计稿要求「期刊式衬线大标题」（Newsreader）+「Inter tabular 数字」，系统字体无法替代。`Noto Sans SC` 引入是为了在 Windows / Mac / Linux 上保持中文权重 500/700/900 的一致渲染（PingFang SC 只在 Mac/iOS 预装，YaHei 在 Windows 上没有 Black weight）。

依据工程规范第 15 章「新增依赖必须可靠 / 活跃 / 官方推荐或事实标准生态」——Google Fonts 三族均满足，引入合规。仅限 `/web` 加载，不影响 Android（系统栈）或 `/owner` 控制台（系统栈）。

## 离线运行

字体进 git，运行时不走外网。`/web` 在断网状态下仍可正常渲染。
