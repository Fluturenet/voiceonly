import logging


LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[35m',
    }
    RESET = '\033[0m'

    def format(self, record):
        original_levelname = record.levelname
        color = self.COLORS.get(original_levelname)
        if color:
            record.levelname = f"{color}{original_levelname}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def build_formatter() -> logging.Formatter:
    return ColorFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)


def configure_named_logger(logger_name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(logger_name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(build_formatter())
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return logger


def configure_uvicorn_loggers(level: int = logging.INFO) -> None:
    formatter = build_formatter()
    for logger_name in ('uvicorn.error', 'uvicorn.access', 'uvicorn.asgi'):
        logger = logging.getLogger(logger_name)
        if logger.handlers:
            for handler in logger.handlers:
                handler.setFormatter(formatter)
        else:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
