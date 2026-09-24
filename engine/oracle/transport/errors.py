"""Typed, credential-free errors at the engine boundary."""

from traceback import extract_tb
from typing import Any

from pydantic import JsonValue

from oracle.models import Contract


class EngineFault(Contract):
    code: str
    message: str
    detail: dict[str, JsonValue]
    recoverable: bool


class EngineError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        self.fault = EngineFault(
            code=code, message=message, detail=detail or {}, recoverable=recoverable
        )
        super().__init__(message)

    def wire(self) -> dict[str, Any]:
        return self.fault.model_dump(mode="json")


def boundary_error(exc: Exception, command: str) -> EngineError:
    if isinstance(exc, EngineError):
        return exc
    # Never serialize arbitrary SDK/validation exception text or input values.
    return EngineError(
        "REQUEST_INVALID" if type(exc).__name__ == "ValidationError" else "ENGINE_INTERNAL",
        "The engine rejected invalid request fields; check the selected inputs."
        if type(exc).__name__ == "ValidationError"
        else f"The {command or 'request'} handler encountered {type(exc).__name__}; copy diagnostics to investigate.",
        {
            "command": command,
            "exception_type": type(exc).__name__,
            "frames": [
                {
                    "file": frame.filename.replace("\\", "/").rsplit("/", 1)[-1],
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in extract_tb(exc.__traceback__)[-8:]
            ],
        },
        False,
    )
