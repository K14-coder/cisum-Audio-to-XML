#!/usr/bin/env bash
# Run Cisum on this computer, then upload an MP3 or MP4 in your browser.
#   ./start.sh            install what's missing (first run: a few minutes), start, open the browser
#   ./start.sh --lite     skip the neural models: much smaller install, rougher results
#   ./start.sh --port N   use another port (default 8000)
#   ./start.sh --no-open  don't open a browser window
# Personal mode: no accounts, and the server only listens on this computer.
set -euo pipefail
cd "$(dirname "$0")"

PORT=8000
LITE=0
OPEN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --lite) LITE=1 ;;
    --port) PORT="$2"; shift ;;
    --no-open) OPEN=0 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see ./start.sh --help)"; exit 2 ;;
  esac
  shift
done

fail() { echo "✗ $*" >&2; exit 1; }
command -v ffmpeg >/dev/null || fail "ffmpeg is missing. macOS: brew install ffmpeg · Ubuntu/Debian: sudo apt install ffmpeg"
command -v node >/dev/null || fail "Node.js is missing. Install Node 20 or newer from https://nodejs.org"
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
[ -n "$PY" ] || fail "Python 3.11 or newer is missing. Install it from https://www.python.org/downloads/"

# Python packages (re-installed only when the requirements change).
VENV=backend/.venv
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
STAMP="$VENV/.cisum-installed"
WANT="$(cat backend/pyproject.toml backend/requirements-ml.txt | cksum | cut -d' ' -f1)-lite$LITE"
if [ "$(cat "$STAMP" 2>/dev/null || true)" != "$WANT" ]; then
  echo "→ Installing Python packages (the first run takes a few minutes)…"
  "$VPY" -m pip --version >/dev/null 2>&1 || "$VPY" -m ensurepip --upgrade >/dev/null
  "$VPY" -m pip install -q --upgrade pip
  if [ "$LITE" = 1 ]; then
    "$VPY" -m pip install -q -e backend
  else
    TORCH_INDEX=""
    # Linux without an NVIDIA GPU: CPU-only PyTorch is a fraction of the download.
    if [ "$(uname)" = "Linux" ] && ! command -v nvidia-smi >/dev/null; then
      TORCH_INDEX="--extra-index-url https://download.pytorch.org/whl/cpu"
    fi
    # shellcheck disable=SC2086
    "$VPY" -m pip install -q $TORCH_INDEX -e "backend[ml]"
    "$VPY" -m pip install -q --no-deps -r backend/requirements-ml.txt
  fi
  echo "$WANT" > "$STAMP"
fi
"$VPY" -c 'import cairosvg' 2>/dev/null || echo "! PDF downloads need the Cairo library. macOS: brew install cairo · Ubuntu/Debian: sudo apt install libcairo2"

# Web app (rebuilt when its sources change).
if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html -print -quit)" ]; then
  echo "→ Building the web app…"
  (cd web && { [ -d node_modules ] || npm ci --no-audit --no-fund --silent; } && npm run build --silent >/dev/null)
fi

mkdir -p backend/data
export CISUM_SINGLE_USER=true
export CISUM_QUEUE=thread
export CISUM_DATABASE_URL="sqlite:///$PWD/backend/data/cisum.db"
export CISUM_STORAGE_DIR="$PWD/backend/data/storage"
export CISUM_WEB_DIST="$PWD/web/dist"

URL="http://localhost:$PORT"
echo "✓ Cisum is running at $URL — press Ctrl+C to stop."
if [ "$OPEN" = 1 ]; then
  (sleep 3; { command -v open >/dev/null && open "$URL"; } || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || true) >/dev/null 2>&1 &
fi
exec "$VPY" -m uvicorn cisum.api.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
