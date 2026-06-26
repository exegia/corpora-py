#!/usr/bin/env bash
# demo/app/scripts/docker-entrypoint.sh
# Prepares the dev container:
# - Ensures Python 3.13 + editable install of the corpora-py library (so exegia.* is importable)
# - Sets up a stable python "shim" the ElectroBun PythonBridge can use in DEV mode
# - Injects optional SSH public key for passwordless login
# - Starts sshd (or the provided CMD)

set -euo pipefail

echo "==> Corpora-Py ElectroBun Demo Dev Container"

# 1. Install Python 3.13 via uv (project requires >= 3.13)
echo "==> Ensuring Python 3.13 via uv..."
uv python install 3.13

# 2. Create a project venv for the demo's Python (used by the bridge in dev mode)
VENV_PATH="/opt/corpora-demo-venv"
echo "==> Creating dev venv at ${VENV_PATH}..."
uv venv --python 3.13 "${VENV_PATH}"

# Activate for the rest of the script
# shellcheck disable=SC1091
source "${VENV_PATH}/bin/activate"

# 3. Install the local library in editable mode so `import exegia` and `exegia.auth` etc. work
echo "==> Installing corpora-py (local) in editable mode..."
uv pip install -e /workspace --quiet

# 4. Create the "resources/python" structure the PythonBridge expects, but pointing at our dev venv
#    This lets the existing python-bridge.ts work with almost no changes when DEV_PYTHON_BIN is set.
RESOURCES_PYTHON="/workspace/demo/app/resources/python"
mkdir -p "${RESOURCES_PYTHON}/bin"

# Symlink the venv python so the bridge can spawn it exactly like a bundled one
ln -sf "${VENV_PATH}/bin/python" "${RESOURCES_PYTHON}/bin/python3" 2>/dev/null || true

# Also expose a lib dir if anything inspects PYTHONHOME (dev shim)
mkdir -p "${RESOURCES_PYTHON}/lib"
ln -sf "${VENV_PATH}/lib" "${RESOURCES_PYTHON}/lib/python3.13" 2>/dev/null || true

echo "==> Dev Python ready at ${VENV_PATH}"
echo "    Bridge will be pointed at ${RESOURCES_PYTHON}/bin/python3 via DEV_PYTHON_BIN"

# 5. SSH key injection (recommended for IDE)
#    Pass SSH_PUBKEY=ssh-ed25519 AAAA... via docker-compose environment or --env
DEV_USER="dev"
DEV_HOME="/home/${DEV_USER}"
mkdir -p "${DEV_HOME}/.ssh"
chmod 700 "${DEV_HOME}/.ssh" || true

if [[ -n "${SSH_PUBKEY:-}" ]]; then
  echo "${SSH_PUBKEY}" >> "${DEV_HOME}/.ssh/authorized_keys"
  echo "==> Injected SSH public key for ${DEV_USER}"
fi

# If you volume-mount your key at runtime:
if [[ -f /host-ssh/id_ed25519.pub ]]; then
  cat /host-ssh/id_ed25519.pub >> "${DEV_HOME}/.ssh/authorized_keys"
fi

touch "${DEV_HOME}/.ssh/authorized_keys"
chmod 600 "${DEV_HOME}/.ssh/authorized_keys" || true
chown -R "${DEV_USER}:${DEV_USER}" "${DEV_HOME}/.ssh" || true

# 6. Prepare the ElectroBun demo app (Bun deps)
cd /workspace/demo/app
if [[ ! -d node_modules ]]; then
  echo "==> Running bun install (first run in container)..."
  bun install
else
  echo "==> node_modules present, skipping bun install"
fi

# 7. Helpful env vars for the PythonBridge (see python-bridge.ts update)
export DEV_PYTHON_BIN="${RESOURCES_PYTHON}/bin/python3"
export DEV_PYTHON_HOME="${RESOURCES_PYTHON}"

# If someone execs into the container we still want these
echo "DEV_PYTHON_BIN=${DEV_PYTHON_BIN}" >> /etc/environment || true
echo "DEV_PYTHON_HOME=${DEV_PYTHON_HOME}" >> /etc/environment || true
echo "PYTHONPATH=/workspace/src" >> /etc/environment || true

echo ""
echo "==================================================="
echo " Dev container ready for ElectroBun + Python"
echo ""
echo " From host (after docker compose up):"
echo "   ssh -p 2222 dev@localhost          # password: dev"
echo ""
echo " Recommended: add to ~/.ssh/config"
echo "   Host corpora-demo"
echo "     HostName localhost"
echo "     Port 2222"
echo "     User dev"
echo ""
echo " Then in VS Code / Cursor: Remote-SSH > Connect to Host > corpora-demo"
echo ""
echo " Inside the container:"
echo "   cd /workspace/demo/app"
echo "   bun run dev          # or bun run dev:hmr"
echo "==================================================="
echo ""

# Hand off to CMD (usually sshd -D)
exec "$@"
