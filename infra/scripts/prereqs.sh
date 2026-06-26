#!/usr/bin/env bash
# Install Terraform, uv, and the AWS CLI without Homebrew (arm64 macOS friendly).
set -euo pipefail
mkdir -p "$HOME/bin"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in arm64|aarch64) ARCH=arm64;; *) ARCH=amd64;; esac

# Install (or upgrade) terraform to >= TF_VER. The S3 backend uses use_lockfile,
# GA only in Terraform 1.10+, so an older terraform (e.g. 1.9.x) must be replaced.
TF_VER="${TF_VER:-1.10.5}"
tf_cur=""
{ command -v terraform >/dev/null 2>&1 || [ -x "$HOME/bin/terraform" ]; } && \
  tf_cur="$( { terraform version 2>/dev/null || "$HOME/bin/terraform" version; } | head -1 | sed -E 's/[^0-9]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/')"
if [ -z "$tf_cur" ] || [ "$(printf '%s\n%s\n' "$tf_cur" "$TF_VER" | sort -V | tail -1)" != "$tf_cur" ]; then
  echo "installing terraform ${TF_VER} (${OS}_${ARCH})${tf_cur:+ — replacing ${tf_cur}}..."
  curl -fsSL -o /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TF_VER}/terraform_${TF_VER}_${OS}_${ARCH}.zip"
  unzip -o /tmp/tf.zip -d "$HOME/bin" >/dev/null && chmod +x "$HOME/bin/terraform" && rm -f /tmp/tf.zip
fi

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "installing awscli (pip --user)..."
  pip3 install --user --quiet awscli
fi

echo ""
echo "Installed. Ensure these are on PATH (add to your shell rc):"
echo '  export PATH="$HOME/bin:$HOME/.local/bin:$HOME/Library/Python/3.9/bin:$PATH"'
export PATH="$HOME/bin:$HOME/.local/bin:$HOME/Library/Python/3.9/bin:$PATH"
terraform version | head -1 || true
aws --version 2>&1 | head -1 || true
