#!/usr/bin/env bash
# Build the Lambda deployment zips (SAP + order-actions + snowflake) for arm64.
# bedrock-demo-infra's release step uploads these to the artifacts S3 bucket;
# Terraform then references them by s3_bucket/s3_key.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build"

rm -rf "$BUILD"
mkdir -p "$BUILD"

build() { # $1 = stub package dir, $2 = zip name, $3+ = pip deps
  local stub="$1" zip="$2"
  shift 2
  local deps=("$@")
  local pkg="$BUILD/${stub}_pkg"
  mkdir -p "$pkg"
  # boto3 is provided by the Lambda runtime, so it is never packaged here.
  python3 -m pip install --quiet --target "$pkg" \
    --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 \
    --only-binary=:all: "${deps[@]}"
  cp -r "$HERE/$stub" "$pkg/$stub"
  (cd "$pkg" && zip -qr "$BUILD/$zip" .)
  echo "built $BUILD/$zip"
}

build sap_stub sap.zip fastapi mangum
build order_actions_stub order_actions.zip fastapi mangum httpx  # httpx: order status from Snowflake data Lambda over HTTP
build snowflake_stub snowflake.zip fastapi mangum pyjwt cryptography  # cryptography ships aarch64 wheels
