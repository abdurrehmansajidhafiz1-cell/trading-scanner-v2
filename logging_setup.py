"""
Logging setup — poore system ke liye ek hi jagah se configure hota hai.
Console pe (GitHub Actions logs mein bhi dikhega) aur ek file mein bhi
(scanner.log) — taake agar kuch fail ho, poori detail milte.
"""

import logging

import config


def setup_logging():
    logger = logging.getLogger("trading_scanner")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    if logger.handlers:
        return logger  # already configured, dobara mat karo

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        file_handler = logging.FileHandler(config.LOG_FILE)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass  # agar file likhne ki permission na ho, sirf console pe chalao

    return logger


# Module import hote hi automatically configure ho jata hai
setup_logging()
