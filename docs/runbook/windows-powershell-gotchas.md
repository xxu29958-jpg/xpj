# Windows PowerShell 5.1 工具坑

本项目后端运维、CI step、本地 git 操作全跑在 **Windows PowerShell 5.1**（`powershell.exe`，非 PS 7、非 WSL、非 Linux shell）上。这套老解释器对 native 命令（git / adb / apksigner / java）的退出码、stderr、参数引用有一串违直觉行为，踩中后产出的是「绿色逻辑 + 红色 step」或「无声跳过」的假信号，本地裸 shell 还常常复现不出。

**做哪类活前读这篇**：写 / 审 `.gitea/workflows/*.yml` 里的 PowerShell step；写 / 改 `backend/scripts/*.ps1`、`scripts/*.ps1`；在 PS 里跑 git 做三端同步、分支判断、ff-merge、commit；用本环境的 Bash 工具配合文件工具改文件。诊断「校验全 OK 但 step 红」「分支明明合了却判成没合」这类怪事时，先回这里对症。

---

## native 命令管道直接接 `Select-Object -First N` 会毁掉退出码

**症状**：一段校验逻辑明明全部打印 OK，step 末尾却 exit 1 变红。CI runner 在 wrapper（`$ErrorActionPreference='stop'` + epilogue `exit $LASTEXITCODE`）下尤其致命——本仓 apksigner 指纹校验那条 step 第一次红就是这么死的。

**根因**：`-First N` 取够 N 条就立刻掐断上游管道。native 进程（apksigner 调的 java）还在往 stdout 写后续证书行，撞上已关闭的管道 → 进程异常退出码 1 → 被 epilogue 当 step 失败传播，而且发生在所有「OK」都打印完之后，所以日志尾部看着全绿。

**正确做法**：先把 native 命令的输出**全量捕获**到变量，再对变量过滤；顺手能拿到真实退出码做检查。这正是 `.gitea/workflows/windows-ci.yml` apksigner step 的写法：

```powershell
$out = & $apksigner.FullName verify --print-certs $apk 2>&1
if ($LASTEXITCODE -ne 0) {
    $out | ForEach-Object { Write-Host $_ }
    throw "apksigner verify failed for $apk (exit $LASTEXITCODE)"
}
$line = $out | Select-String -Pattern "certificate SHA-256 digest" | Select-Object -First 1
```

注意 `Select-Object -First 1` 是安全的——它作用在已经驻留内存的 `$out` 数组上，没有 native 进程在另一端被掐。危险的只是 native 命令**直接**接 `-First`。

**铁律**：native 命令（含 .bat / .exe）先 `$out = & cmd ...` 全量捕获，绝不直接管到 `Select-Object -First`。

---

## EAP=Stop 下任何显式 stderr 重定向把 native 噪声变 terminating

**症状**：脚本在第一行预期噪声上就被掀进 catch / 直接终止。例如 adb 在模拟器注册期间正常会往 stderr 写 `device offline` / `not found`，CI 的 connected lane run #103 就死在第一次 boot 轮询。

**根因**：CI runner wrapper 设了 `$ErrorActionPreference='Stop'`。在这个语境下，对 native 命令做**任何**显式 stderr 重定向——`2>$null` 和 `2>&1` **一样危险**——都会把 native 的每一行 stderr 包装成 terminating `ErrorRecord`，第一行就终止脚本。别误信「`2>&1` 安全」：它之前没炸只是因为那个命令恰好没往 stderr 写东西。**不重定向的 native stderr 不会被包装**（透传给宿主），那是安全的。

**正确做法**：在该 step 体内显式降级 EAP，前提是这个 step 的所有失败路径都已用 `throw` / `$LASTEXITCODE` 显式控制；真正需要抛错的 cmdlet（如 `Start-Process`）单独加 `-ErrorAction Stop`。`android-connected.yml` 的 emulator step 就是模板：

```powershell
$ErrorActionPreference = "Continue"
# ... 调 adb / emulator，预期 stderr 噪声不再终止脚本 ...
$proc = Start-Process -FilePath $emu -ArgumentList ... -ErrorAction Stop
```

**铁律**：在 EAP=Stop 的 wrapper 里调爱写 stderr 的 native 命令（adb / git / java），要么完全不重定向 stderr，要么整个 step 显式 `$ErrorActionPreference = 'Continue'` 并自己 throw 兜底；`2>$null` 不是消音器，是引信。

---

## 对 git 别用 `2>&1 | Out-Null` 再接 `$?` 链

**症状**：`git checkout` / `git merge --ff-only` 这类操作实际成功了，但链上后续命令被静默跳过——本地 main 没前进、`git push` 报 up-to-date、工作树看着像切回了改动前的状态（改动其实安全在 merge commit 里，但流程断了还无声）。

**根因**：git 把正常进度信息（`Switched to branch ...`）写在 **stderr**。`2>&1` 把它合进 stdout 后，PS 5.1 把这些行包装成 `NativeCommandError` → `$?` 变 `$false` → `; if ($?) { ... }` 链上后续命令永不执行。

**正确做法**：git 命令**直接跑**（本环境的 PowerShell / Bash 工具已分开捕获 stderr，无需重定向）；要静音也别拿 `$?` 当成功信号。成功与否用**状态命令**验证：

```powershell
git checkout main
git merge --ff-only local-gitea/main
# 用状态命令核实，而不是退出链：
git rev-parse main          # 比对预期 SHA
git status --porcelain      # 应为空
```

**铁律**：git 的成败永远用 `git rev-parse` / `git status` / `$LASTEXITCODE` 核实，绝不靠 `2>&1 | Out-Null` + `$?` 链判定。

---

## `if (git ...)` 按 stdout 文本判真假，不是退出码

**症状**：`if (git merge-base --is-ancestor A B) { ... }` 永远走 else——分支明明已经在 main 里，却被判成「NOT in main」。

**根因**：PS 的 `if` 对 native 命令求值的是它的 **stdout 文本**，不是退出码。`--is-ancestor` 成功时 exit 0 且**无任何输出** → 空字符串 = falsy → 恒走 else。`diff --quiet` 这类「静默成功」命令同理。

**正确做法**：静默成功的 git 判断命令跑完后查 `$LASTEXITCODE`，别包在 `if (git ...)` 里。这也是全仓 .ps1 的统一写法（`if ($LASTEXITCODE -ne 0) { ... }`）：

```powershell
git merge-base --is-ancestor $branch main
if ($LASTEXITCODE -eq 0) {
    # branch 已在 main 里
}
```

额外注意：`git branch -d` 的「已合并」检查是对照**当前 HEAD**而非 main——HEAD 在别的分支时会误报 not fully merged。先用 `--is-ancestor` 对 main 验证，再 `-D` 删。

**铁律**：静默成功的 git 命令（`--is-ancestor` / `diff --quiet`）一律跑完查 `$LASTEXITCODE -eq 0`，不放进 `if (git ...)`。

---

## 一个 step 里串多条 native 命令，前面的非零退出会被后面那条覆盖

**症状**：一个 step 顺序跑了好几个 `powershell -File xxx.ps1`，**第一个明明 fail 了**（日志里能看到它抛的错），step 却照样绿。本仓 `check_text_encoding.ps1` 编码硬门就这么**静默死了好几天**——CI run #83 的 Backend job 是 success，可它的日志里清清楚楚打着 `发现疑似乱码片段 '灏'`，gate 实际从没拦住过任何东西。

**根因**：CI runner 的 wrapper 只在末尾看一次 `exit $LASTEXITCODE`。PS 5.1 里 native 命令（含 `powershell -File ...` 这种子进程）的**非零退出不触发 terminating error**（`$ErrorActionPreference='stop'` 只管 cmdlet），脚本继续往下跑；下一条 native 命令成功退出把 `$LASTEXITCODE` **重置成 0**，后面纯 cmdlet 又不动它。于是 wrapper 末尾读到的是**最后一条** native 命令的码——前面任何一条的失败都被无声吞掉。只有排在最后的那条 native 命令的失败才真正能让 step 红。

**正确做法**：每条 native 命令后面**立刻**显式查退出码并传播，别攒到末尾：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
powershell -ExecutionPolicy Bypass -File scripts\check_dependency_versions.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

这跟「git 静默成功命令查 `$LASTEXITCODE`」是同一条铁律的另一面：native 命令的成败**只能用紧跟其后的 `$LASTEXITCODE` 判定**，不能假设它会自动让 step 失败。`backend/tests/test_audit_ci_gap.py` 有一条回归测试钉死这两条 gate 调用后必须紧跟 `$LASTEXITCODE` 守卫，防 gate 再次被无声删护栏后复活原 bug。

**铁律**：一个 step 串多条 native 命令，每条后面紧跟 `if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }`；绝不靠 wrapper 末尾那一次 `exit $LASTEXITCODE` 兜前面所有命令。

---

## 含内嵌双引号的 commit message 走 `-m` 会被切碎

**症状**：`git commit -m @'...'@`（here-string）里若 message 含内嵌双引号（如「替换 "v1.0 迁移" 字样」），git 把后半段当 pathspec，报 `error: pathspec '...' did not match`。

**根因**：PS 5.1 向 native exe 传参时按**自身规则重新引用**整条命令行。here-string 的字面量保真只到 PowerShell 层，跨进程边界时内嵌的 `"` 不被转义，参数被拆断。

**正确做法**：多行 / 含引号的 commit message 一律走文件，用 no-BOM UTF-8 写出，再 `-F` 传：

```powershell
$msg = @'
fix(...): 标题

正文里出现 "带引号" 也安全。
'@
$path = Join-Path (git rev-parse --git-dir) "COMMIT_TBX.txt"
[System.IO.File]::WriteAllText($path, $msg, (New-Object System.Text.UTF8Encoding($false)))
git commit -F $path
[System.IO.File]::Delete($path)
```

临时文件放在 `.git\` 下（天然不会被误 `git add`；别放 `$env:TEMP`——后续清理时 `Remove-Item $var` 可能撞本环境沙箱的 `/` 守卫，用 `[System.IO.File]::Delete(<绝对路径>)`）。同理适用 gitea API 的 PR body（`curl --data-binary @file`）。

**铁律**：commit message / PR body 一律 `WriteAllText`（no-BOM）+ `git commit -F` / `--data-binary @file`，从不内联进 `-m`。

---

## `.ps1` 必须 UTF-8 with BOM，`.env` 必须无 BOM

**症状**：PS 5.1 读不带 BOM 的 UTF-8 文件时**默认按 ANSI 解析**，中文全乱码；脚本里的中文提示、乱码检测、字段名全错位。反过来，`.env` 带了 BOM 会让首个 key 被污染。

**根因**：PS 5.1 没有「默认 UTF-8」，BOM 是它判定编码的唯一可靠信号。本仓把这条钉成 CI 硬门：`scripts/check_text_encoding.ps1` 在 CI / verify 都跑，对 `.ps1` 强制要求 BOM（`bytes[0..2] == EF BB BF`），违反即 fail，还会扫已知 mojibake 片段（`灏`/`銆`/`锛`…）兜底。

**正确做法**：
- 写 / 存 `.ps1` 用 **UTF-8 with BOM**；`.env` 用**不带 BOM** 的 UTF-8。
- 脚本里读文件**显式指定编码**，全仓统一这么写：

```powershell
$content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
```

- PS step 链接命令**不能用 `&&` / `||`**（PS 5.1 语法错），用 `; if ($?) { ... }`（注意此处 `$?` 用在 cmdlet 上是可靠的；坑只在前述 native + 重定向场景）。

**铁律**：`.ps1` = UTF-8 with BOM、`.env` = 无 BOM；脚本读文件必带 `-Encoding UTF8`，链命令用 `; if ($?)` 不用 `&&`。

---

## Bash 工具 `cd` 后文件工具一律用绝对路径

**症状**：在某条 Bash 命令里 `cd` 进子目录后，传给 Write/Edit/Read 的**相对路径**解析漂移——repo-root 相对的 `backend\tests\x.py` 漏写到 `backend/backend/tests/x.py`，随后同样相对路径的 Edit 报「File does not exist」，而 Glob 仍按 tracked 路径报告，三方打架。

**根因**：本环境（Windows + Bash 工具）里 Bash 的 cwd 与文件工具的路径基准在 `cd` 后会漂移，且 cwd **跨 tool call 不可靠地保持**。

**正确做法**：
- Write / Edit / Read **一律用绝对路径**（`E:\projects\xiaopiaojia\backend\app\x.py`），尤其在本 session 跑过 `cd` 之后。
- Bash 用单条 `cd /abs && cmd`，别假设 cwd 跨调用保持；判路径前先 `pwd`。
- **Bash 的 `&&` / `;` 链不要以一个「合法地非零退出」的命令结尾**（如 `ls <本应已删的东西>`、`grep <预期无匹配>`）——非零的尾命令会把整条 Bash 调用标成 errored，并**取消同一条消息里并行的其它 tool call**。
- 症状识别：Glob 找得到某文件但 `ls` / ruff / pytest 说找不到，或 Write「成功」但工具看不到 → 怀疑 `backend/backend/` 这类相对路径泄漏，用绝对路径核实并 `mv` 归位。

**铁律**：文件工具用绝对路径，Bash 链别以会非零退出的命令结尾。

---

## 记忆勘误

逐站点核验五条源记忆与真实文件（`scripts/check_text_encoding.ps1`、两个 `.gitea/workflows/*.yml`、全仓 `*.ps1`、`AGENTS.md` / `ENGINEERING_RULES.md` §14），**所有 gotcha 描述均与真实文件一致**，无需勘误：

- apksigner 全量捕获 + `Select-Object -First` 的坑，与 `windows-ci.yml` L443–470 注释和实现逐字吻合。
- adb / emulator 的 EAP=Stop stderr 包装坑，与 `android-connected.yml` L100–142 吻合（实锤为 run #103）。
- `$LASTEXITCODE` 判定静默成功命令、`.ps1` 必带 BOM + `-Encoding UTF8`、`&&` 不可用、commit message 走 `-F`、文件工具绝对路径——均与全仓 .ps1 现行写法及 §14「Windows PowerShell 5.1 + UTF-8 BOM」条款一致。

（提示：源记忆的 PR 编号、run 号等历史细节属点-in-time 观测，本 runbook 已改写为可操作的稳定规则，未原样搬运易过期的数字。）
