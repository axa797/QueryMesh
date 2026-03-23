"""Helpers for LLM JSON responses (markdown fences, etc.)."""


def strip_markdown_fences(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
