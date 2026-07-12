import logging


def configure_logger(instance: logging.Logger) -> None:
    """Configure a custom logger."""

    # Create a handler (console output in this case)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(instance.level)

    # Create a formatter and set it to the handler
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)

    # Add the handler to the logger
    if not instance.hasHandlers():
        instance.addHandler(console_handler)

    # Disable propagation to avoid log duplication via uvicorn
    instance.propagate = False

def logger(name: str = __name__, level = logging.INFO) -> logging.Logger:
    # Create a logger
    instance = logging.getLogger(name)
    instance.setLevel(level)
    configure_logger(instance)
    return instance

corpora_logger = logger()

__all__ = ["corpora_logger"]
