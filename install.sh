#!/usr/bin/env bash
# Configure the ArenaX Robotics environment with uv and optionally launch the editor.
# uv manages the project-local .venv and can download a compatible Python runtime,
# so the host Python does not need the venv/ensurepip system package.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
RUN_EDITOR=0
PYTHON_VERSION="3.12"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --run             install dependencies and launch the PyQt editor
  --python VERSION  choose the Python version managed by uv (default: 3.12)
  -h, --help        show this help message

The environment is always created in the repository-local .venv directory.
If uv is not installed, the official installer is downloaded from astral.sh.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

find_uv() {
  if has_command uv; then
    command -v uv
    return 0
  fi
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

args=("$@")
for ((index = 0; index < ${#args[@]}; index++)); do
  case "${args[index]}" in
    --run)
      RUN_EDITOR=1
      ;;
    --python)
      ((index + 1 < ${#args[@]})) || die "--python requires a version argument, for example --python 3.12"
      PYTHON_VERSION="${args[index + 1]}"
      [[ -n "$PYTHON_VERSION" ]] || die "Python version cannot be empty."
      index=$((index + 1))
      ;;
    --python=*)
      PYTHON_VERSION="${args[index]#*=}"
      [[ -n "$PYTHON_VERSION" ]] || die "Python version cannot be empty."
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: ${args[index]}" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! UV_BIN="$(find_uv)"; then
  if has_command curl; then
    echo "uv was not found; installing it with the official installer..."
    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
  elif has_command wget; then
    echo "uv was not found; installing it with the official installer..."
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "uv is not installed and neither curl nor wget is available to install it."
  fi
  UV_BIN="$(find_uv)" || die "uv installation finished, but the uv executable was not found."
fi

echo "Using $($UV_BIN --version)"
echo "Creating or reusing Python $PYTHON_VERSION environment: $VENV_DIR"
"$UV_BIN" venv --python "$PYTHON_VERSION" --allow-existing "$VENV_DIR" \
  || die "Could not create the .venv with uv. Check the Python version and network connection."

VENV_PYTHON="$VENV_DIR/bin/python"
[[ -x "$VENV_PYTHON" ]] || die "uv did not create a usable Python executable at $VENV_PYTHON."

echo "Installing ArenaX Robotics and its dependencies..."
"$UV_BIN" pip install --python "$VENV_PYTHON" --editable "$ROOT_DIR"

echo "Running installation checks..."
echo "  Checking runtime dependencies..."
"$VENV_PYTHON" -c 'import mujoco, numpy, onnxruntime, yaml; import PyQt5'
echo "  Checking terrain CLI..."
"$VENV_PYTHON" -m terrain_generator.cli --help >/dev/null
echo "  Installation checks passed."

echo "Installation complete. Activate with:"
echo "  source \"$VENV_DIR/bin/activate\""

if [[ "$RUN_EDITOR" -eq 1 ]]; then
  echo "Launching the ArenaX Robotics editor..."
  exec "$VENV_PYTHON" -m terrain_generator.cli --edit --output "$ROOT_DIR/generated/editor"
fi

echo "Launch the editor with:"
echo "  \"$VENV_PYTHON\" -m terrain_generator.cli --edit --output generated/editor"
