# Web fonts

`/web` 产品页、连接入口与币种设置使用同一份本地自托管字体定义 `fonts.css`。Android 与 `/owner` 使用系统字体，与本目录无关。

## 字体清单

| 字体 | 用途 | 权重 |
|---|---|---|
| Noto Sans SC（Ticketbox Sans） | 中文正文与界面 | variable 400–800 |
| Inter（Ticketbox Figures） | tabular 数字、英文标签 | variable 400–800 |

## 下载

```powershell
pwsh scripts/download-fonts.ps1
# 本机网络需要代理时，可传 -Proxy http://127.0.0.1:7897
```

脚本从 Google Fonts CSS API 获取两族字体的完整分片集合，保留每片的 `unicode-range` 与连续字重范围。字体文件以内容 SHA-256 的前 16 位命名，生成的 CSS 只引用本地文件，浏览器按页面实际用字加载需要的分片。

不能再只选择包含 `U+4E00` 的一个分片：此前该文件只有 277 个字形，连“小票夹”“预算”等常用界面文字都依赖系统补字，导致同页中文混排。三个不同字重的文件名也不能代替可变字体范围声明。

重新生成后，应核对实际字形覆盖、浏览器字体来源、真实页面换行及字体请求；移除已被替代且没有消费者的旧文件。本目录不保留已经退出当前产品样式的 Newsreader。

## 来源与许可

- [Google Fonts CSS API](https://developers.google.com/fonts/docs/css2)
- [Noto Sans SC](https://github.com/google/fonts/tree/main/ofl/notosanssc)，许可见 `NotoSansSC-OFL.txt`。
- [Inter](https://github.com/google/fonts/tree/main/ofl/inter)，许可见 `Inter-OFL.txt`。

## 离线运行

字体与 CSS 随应用打包，运行时不访问 Google。访问本地后端无需外网即可加载字库；字体自身不包含的字符继续使用浏览器系统字体。
