from dataclasses import dataclass


@dataclass
class AppError(Exception):
    code: str
    message: str
    status: int = 400
