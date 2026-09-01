#!/usr/bin/env bash
# Create the project virtual environment, install ArenaX Robotics, and optionally launch
# the graphical editor.  The script is intentionally dependency-light: it
# only requires Python 3.10+ and a working venv module.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
RUN_EDITOR=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [--run]

  --run    install dependencies and launch the PyQt editor
EOF
}

for arg in "$@"; do
  case "$arg" in
    --run)
      RUN_EDITOR=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Python 3.10 or newer is required but was not found." >&2
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; sys.exit("Python 3.10+ is required") if sys.version_info < (3, 10) else None'

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating virtual environment: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -c 'import sys; sys.exit("The existing .venv must use Python 3.10+.") if sys.version_info < (3, 10) else None'
echo "Installing ArenaX Robotics and its dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e "$ROOT_DIR"

echo "Installation complete. Activate with:"
echo "  source \"$VENV_DIR/bin/activate\""

if [[ "$RUN_EDITOR" -eq 1 ]]; then
  echo "Launching the ArenaX Robotics editor..."
  exec "$VENV_PYTHON" -m terrain_generator.cli --edit --output "$ROOT_DIR/generated/editor"
fi

echo "Launch the editor with:"
echo "  \"$VENV_PYTHON\" -m terrain_generator.cli --edit --output generated/editor"
