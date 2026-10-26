#!/usr/bin/env bash
# 课表转日历 skill — 本地安装脚本（macOS / Linux）
#
#   bash install.sh                 # 自动选择 skills 目录
#   bash install.sh ~/my/skills     # 指定目录
#
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="syllabus-to-ics"

# 1. 找目标目录
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  for d in "$HOME/.codebuddy/skills" "$HOME/.claude/skills" "$HOME/.config/skills"; do
    if [ -d "$d" ]; then TARGET="$d"; break; fi
  done
fi
if [ -z "$TARGET" ]; then
  TARGET="$HOME/.codebuddy/skills"
  echo "未找到现成的 skills 目录，将新建：$TARGET"
fi
mkdir -p "$TARGET"

DEST="$TARGET/$NAME"
if [ -d "$DEST" ]; then
  echo "已存在 $DEST，先备份为 ${DEST}.bak"
  rm -rf "${DEST}.bak"
  mv "$DEST" "${DEST}.bak"
fi

# 2. 复制（排除版本库与缓存）
mkdir -p "$DEST"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' "$SRC"/ "$DEST"/
else
  (cd "$SRC" && tar --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' -cf - .) | (cd "$DEST" && tar -xf -)
fi
echo "✅ 已安装到 $DEST"

# 3. 自检
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "⚠ 没找到 python3，脚本无法运行。装一个 Python 3.9+ 再来。"
  exit 1
fi
echo "使用 $($PY --version 2>&1)"

(cd "$DEST" && "$PY" -m unittest discover -s tests 2>&1 | tail -3)

echo
echo "下一步："
echo "  1) 把课表 PDF 丢给 AI，说“按 syllabus-to-ics 流程生成日历”"
echo "  2) 解析 PDF 需要：$PY -m pip install pymupdf"
echo "  3) 手动跑：$PY $DEST/scripts/build.py -c <配置>.json -o 课表.ics"
