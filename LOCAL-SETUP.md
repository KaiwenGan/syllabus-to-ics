# 本地安装与使用

这份包解压后是完整可用的 skill，不依赖我的会话。三步走完。

## 一、装进你电脑

### macOS / Linux

```bash
cd syllabus-to-ics        # 解压后进入这个目录
bash install.sh
```

脚本会：找 skills 目录（`~/.codebuddy/skills` 或 `~/.claude/skills`）→ 复制 → 跑 7 项自检。
已存在旧版本会先备份成 `.bak`，不会覆盖丢失。

指定别的位置：

```bash
bash install.sh ~/我的目录/skills
```

### Windows（PowerShell）

```powershell
cd syllabus-to-ics
.\install.ps1
```

如果提示"禁止运行脚本"，先在这个窗口执行一次：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 二、验证

不用等 AI，先自己确认能跑：

```bash
python -m unittest discover -s tests
```

看到 `Ran 7 tests ... OK` 就对了。

## 三、用起来

把课表 PDF 丢给本地的 AI，说：

> 按 syllabus-to-ics 的流程，把这份课表生成日历

或者完全手动：

```bash
python -m pip install pymupdf                              # 只有读 PDF 需要
python scripts/parse_text.py --pdf 我的课表.pdf -o draft.json
# 编辑 draft.json，补 term.first_monday / periods / seasons（README 有说明）
python scripts/build.py -c draft.json -o 课表.ics -r 报告.md --html 总表.html
python scripts/audit.py -c draft.json -i 课表.ics           # 必须显示「缺失 0」
```

生成的 `课表.ics`：iPhone 上点开即导入，或 AirDrop 到手机、或用 Mac 日历"文件 → 导入"。

## 需要注意

- **`periods` 必须填**。每所学校的作息不同，仓库里的示例是虚构时间，直接套用会全错。
- **`term.first_monday` 填第一教学周的周一**，不是报到日。学期总周数在 `term.weeks`。
- **冬夏令时**：`seasons.winter_ranges` 填作息表两栏的生效区间，如 `[["10-01","04-30"]]`。
- **不要手工改 `.ics`**。改配置重新生成，`audit.py` 会拦住错误。
- 导入前如果之前导过旧版，先在日历 App 里删掉旧的那组事件——UID 变了会并存成重复。

## 想推到 GitHub 给朋友

```bash
git init -b main
git add -A
git commit -m "feat: 课表转日历 skill"
gh repo create syllabus-to-ics --public --source=. --push
# 没装 gh：去 github.com/new 建空仓库（不要勾 README），再加 remote 推送
```

推完给朋友这个地址，AI 能直接读：

```
https://raw.githubusercontent.com/KaiwenGan/syllabus-to-ics/main/SKILL.md
```

## 卸载

```bash
rm -rf ~/.codebuddy/skills/syllabus-to-ics      # 或 ~/.claude/skills/...
```

Windows：

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.codebuddy\skills\syllabus-to-ics"
```
