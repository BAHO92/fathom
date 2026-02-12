#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/BAHO92/fathom.git"
SKILL_DIR="${HOME}/.claude/skills/fathom"

echo "=== fathom installer ==="
echo ""

command -v git >/dev/null 2>&1 || { echo "Error: git is required but not installed."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required but not installed."; exit 1; }

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]; }; then
    echo "Error: Python 3.8+ required (found $PYTHON_VERSION)"
    exit 1
fi

mkdir -p "${HOME}/.claude/skills"

if [ -d "$SKILL_DIR" ]; then
    echo "Updating existing installation..."
    cd "$SKILL_DIR"
    git pull --ff-only
else
    echo "Installing fathom..."
    git clone "$REPO" "$SKILL_DIR"
fi

echo "Installing dependencies..."
pip3 install --quiet requests beautifulsoup4 lxml pyyaml

echo ""
echo "=== Installation complete ==="
echo "fathom installed at: $SKILL_DIR"
echo ""
echo "Start using fathom in Claude Code:"
echo '  "실록에서 송시열 검색해줘"'
echo '  "승정원일기 현종 3년 수집해줘"'
echo '  "문집 ITKC_MO_0367A 전체 수집해줘"'
