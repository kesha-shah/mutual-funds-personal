#!/usr/bin/env bash
# Launch both processes the app needs (the README runs these in two terminals):
#   1. Streamlit dashboard backend on :8501 (internal only)
#   2. FastAPI auth gateway on :8000 (the port we expose)
# The gateway can't render without Streamlit, and Streamlit can't authenticate
# without the gateway — so if either dies, tear the whole container down.
set -euo pipefail

# A config.yaml must exist (gitignored). If none is mounted, fall back to the
# example so first boot doesn't crash — but warn loudly, since admin_email
# still needs to be set for admin signup to work.
if [[ ! -f /app/config.yaml ]]; then
  echo "WARNING: no config.yaml mounted — copying config.example.yaml. Set admin_email!" >&2
  cp /app/config.example.yaml /app/config.yaml
fi

# CAMS runs Playwright headful (headless trips reCAPTCHA), so give the
# displayless container a virtual framebuffer for Chromium.
Xvfb :99 -screen 0 1280x1024x24 >/dev/null 2>&1 &
xvfb_pid=$!
export DISPLAY=:99

term() {
  echo "Shutting down..." >&2
  kill -TERM "${streamlit_pid:-}" "${uvicorn_pid:-}" "${xvfb_pid:-}" 2>/dev/null || true
  wait
}
trap term TERM INT

sleep 1  # let Xvfb bind :99 before Chromium uses it

streamlit run ui/app.py &
streamlit_pid=$!

uvicorn auth_server.main:app --host 0.0.0.0 --port 8000 &
uvicorn_pid=$!

# Exit as soon as either process exits, propagating its status.
wait -n
status=$?
echo "A process exited (status $status) — stopping container." >&2
term
exit "$status"
