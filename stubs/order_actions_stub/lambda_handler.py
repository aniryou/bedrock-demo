"""AWS Lambda entrypoint for the order-actions API (deploy path)."""

from __future__ import annotations

from mangum import Mangum

from .app import app

handler = Mangum(app)
