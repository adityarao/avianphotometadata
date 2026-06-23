#!/bin/bash
# © Aditya Rao (aditya.r.rao@gmail.com)
# ---------------------------------------------------------------
# Avian Photo Metadata Assistant — launcher
# Run from the project root:  ./run.sh
# ---------------------------------------------------------------
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

# 1. Find a Python that has tkinter (_tkinter) available.
#    python@3.12 and python@3.13 bundle Tk on Homebrew; 3.14 needs a separate formula.
#    We probe each candidate and pick the first one that imports _tkinter successfully.
find_python_with_tk() {
  local candidates=(
    /opt/homebrew/opt/python@3.12/bin/python3.12
    /opt/homebrew/opt/python@3.13/bin/python3.13
    /usr/local/opt/python@3.12/bin/python3.12   # Intel Homebrew
    /usr/local/opt/python@3.13/bin/python3.13
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
    python3
  )
  for py in "${candidates[@]}"; do
    if command -v "$py" &>/dev/null; then
      if "$py" -c "import _tkinter" 2>/dev/null; then
        echo "$py"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON=$(find_python_with_tk || true)

if [ -z "$PYTHON" ]; then
  echo ""
  echo "❌  No Python with Tk support found."
  echo ""
  echo "    Fix with one of these commands:"
  echo "       brew install python@3.12              # recommended"
  echo "       brew install python-tk@3.14           # if you want to keep 3.14"
  echo ""
  echo "    Then delete .venv/ and re-run:  rm -rf .venv && ./run.sh"
  exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "🐍  Python $PY_VERSION  ($PYTHON)"

# 2. Check ExifTool
if ! command -v exiftool &>/dev/null; then
  echo ""
  echo "⚠️   ExifTool not found."
  echo "    Install it with:  brew install exiftool"
  echo "    The app will still launch but EXIF extraction will be disabled."
  echo ""
else
  echo "🔧  ExifTool $(exiftool -ver)"
fi

# 3. Create virtualenv on first run
if [ ! -d "$VENV_DIR" ]; then
  echo ""
  echo "📦  Creating virtual environment..."
  "$PYTHON" -m venv "$VENV_DIR"
  echo "    Virtual environment created at .venv/"
fi

VENV_PYTHON="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"

# 4. Install / upgrade deps into the venv
echo ""
echo "📦  Checking Python dependencies..."
"$VENV_PIP" install --quiet --upgrade pip
"$VENV_PIP" install --quiet -r "$PROJECT_DIR/requirements.txt"
echo "    Dependencies OK"

# 5. Launch
echo ""
echo "🦅  Launching Avian Photo Metadata Assistant..."
echo ""
cd "$PROJECT_DIR/src"
"$VENV_PYTHON" main.py
