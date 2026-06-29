#!/usr/bin/env python3
"""
Helper for the consumer/client app to ensure the embedded Python runtime is present.

Usage (example for client app code):
    from scripts.ensure_python_runtime import ensure_python_runtime
    ensure_python_runtime()  # or with target_dir

Logic:
- Check if <target>/bin/python3 exists and is executable.
- If yes: "already have", do nothing (or 'load what's there').
- If no: download the prebuilt tarball for the platform and extract.

For 'only load what's missing':
- Currently treats the runtime as atomic (full bundle or nothing).
- If you split features into multiple bundles later, extend the check (e.g. check for specific .so or packages).

You will need to:
- Host the python-runtime-*.tar.gz (produced by python -m scripts.build.client_runtime or python -m scripts.build.embedded --full)
  somewhere (GitHub Releases, S3, your CDN).
- Update DOWNLOAD_BASE_URL below.
- Adapt for your app's platform detection and storage location (e.g. app support dir instead of next to binary).

The ElectroBun client should call this before initializing PythonBridge if full features are opted in.
"""
