def main() -> dict:
    """Demo entrypoint called from the ElectroBun PythonBridge."""
    return {
        "status": "ok",
        "message": "Hello from shared.auth (running via the demo app)",
        "python_version": __import__("sys").version,
    }
