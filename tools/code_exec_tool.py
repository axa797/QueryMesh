"""E2B sandbox runner for Python only (spec §6.3) — **call from code_agent only**."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from api.settings import get_settings
from e2b import AsyncSandbox
from e2b.exceptions import SandboxException, TimeoutException

log = logging.getLogger(__name__)

_TRUNC = "[truncated]"

# Per-process limiter (replica-level cap when running one worker per replica).
_exec_sem: asyncio.Semaphore | None = None


def _get_exec_semaphore() -> asyncio.Semaphore:
    global _exec_sem
    if _exec_sem is None:
        n = max(1, get_settings().code_exec_max_concurrent)
        _exec_sem = asyncio.Semaphore(n)
    return _exec_sem


def cap_combined_output(stdout: str, stderr: str, max_bytes: int) -> tuple[str, str]:
    """Trim stdout+stderr to a single byte budget (spec: combined capture cap)."""
    enc = "utf-8"
    so_b = stdout.encode(enc, errors="replace")
    se_b = stderr.encode(enc, errors="replace")
    if len(so_b) + len(se_b) <= max_bytes:
        return stdout, stderr
    m_b = _TRUNC.encode(enc)
    budget = max(0, max_bytes - len(m_b))
    if len(so_b) >= budget:
        return so_b[:budget].decode(enc, errors="replace") + _TRUNC, ""
    rest = budget - len(so_b)
    out_s = so_b.decode(enc, errors="replace")
    err_part = se_b[:rest].decode(enc, errors="replace")
    if len(se_b) > rest:
        err_part += _TRUNC
    return out_s, err_part


async def exec_python(code: str) -> dict[str, Any]:
    """
    Run ``code`` in an E2B sandbox (no internet, no injected GCP creds).

    Returns a dict suitable for ``execution`` in code-agent JSON:
    stdout, stderr, exit_code, source (e2b_ok | skipped_no_key | e2b_timeout | e2b_error).
    """
    settings = get_settings()
    if not (settings.e2b_api_key or "").strip():
        env_raw = os.environ.get("E2B_API_KEY")
        log.warning(
            "e2b skipped_no_key cwd=%s env_E2B_API_KEY_set=%s env_empty_or_missing=%s "
            "(process env overrides .env; unset empty E2B_API_KEY to use .env file)",
            os.getcwd(),
            env_raw is not None,
            env_raw is not None and not str(env_raw).strip(),
        )
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "source": "skipped_no_key",
        }

    text = code.strip()
    if len(text) > settings.code_exec_max_code_chars:
        return {
            "stdout": "",
            "stderr": (
                f"Code exceeds max length ({settings.code_exec_max_code_chars} chars); "
                "not executed."
            ),
            "exit_code": None,
            "source": "validation_error",
        }

    max_out = settings.code_exec_output_max_bytes
    wall = settings.code_exec_wall_seconds
    lifetime = max(30, int(settings.e2b_sandbox_timeout_seconds))
    tmpl = (settings.e2b_template_id or "").strip() or None

    sem = _get_exec_semaphore()
    async with sem:
        try:
            sandbox = await AsyncSandbox.create(
                template=tmpl,
                timeout=lifetime,
                allow_internet_access=False,
                envs={},
                api_key=settings.e2b_api_key,
            )
            async with sandbox:
                await sandbox.files.write("/tmp/querymesh_user.py", text)
                try:
                    res = await sandbox.commands.run(
                        "python3 /tmp/querymesh_user.py",
                        timeout=wall,
                    )
                except TimeoutException as e:
                    log.warning("E2B command wall timeout: %s", e)
                    return {
                        "stdout": "",
                        "stderr": str(e),
                        "exit_code": None,
                        "source": "e2b_timeout",
                    }
                out, err = cap_combined_output(res.stdout or "", res.stderr or "", max_out)
                return {
                    "stdout": out,
                    "stderr": err,
                    "exit_code": int(res.exit_code),
                    "source": "e2b_ok",
                }
        except TimeoutException as e:
            log.warning("E2B sandbox timeout: %s", e)
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": None,
                "source": "e2b_timeout",
            }
        except SandboxException as e:
            log.warning("E2B error: %s", e)
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": None,
                "source": "e2b_error",
            }
        except Exception as e:
            log.exception("Unexpected E2B failure")
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": None,
                "source": "e2b_error",
            }
