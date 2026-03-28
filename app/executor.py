"""
executor.py: ejecución local controlada para Edge BI.

Encapsula:
- namespace controlado
- captura de stdout
- propagación de errores con mensaje claro
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ExecResult:
    stdout: str
    error: Optional[Exception] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def safe_exec(code: str, namespace: Dict[str, Any]) -> ExecResult:
    """
    Ejecuta `code` usando `exec` con captura de stdout.
    Nota: esto NO es un sandbox seguro; solo centraliza el flujo para Edge BI.
    """
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(code, namespace)
        return ExecResult(stdout=output.getvalue(), error=None)
    except Exception as e:
        return ExecResult(stdout=output.getvalue(), error=e)

