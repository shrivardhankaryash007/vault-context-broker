"""Local summarization strategies for context packs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from vault_context_mcp.config import SummarizerConfig
from vault_context_mcp.schemas import RetrievedChunk
from vault_context_mcp.utils import truncate_words

_SESSION_EXTRACT_SCHEMA = """{
  "summary": "1-3 sentence summary of what was accomplished",
  "key_takeaways": ["insight 1"],
  "decisions": ["decision 1"],
  "open_questions": ["question 1"],
  "next_actions": ["action 1"]
}"""

SIGNAL_PREFIXES = ("-", "*", ">", "todo", "next", "decision", "constraint", "question")
SIGNAL_WORDS = (
    "current",
    "state",
    "decision",
    "decided",
    "constraint",
    "must",
    "should",
    "todo",
    "next",
    "open question",
    "blocked",
    "risk",
    "important",
)


class Summarizer:
    """Prepare compact context text without solving the user's task."""

    def __init__(self, config: SummarizerConfig) -> None:
        self.config = config

    def summarize(self, task: str, chunks: list[RetrievedChunk], max_tokens: int) -> str:
        """Summarize retrieved chunks with configured provider and fallback."""

        if self.config.provider == "ollama":
            ollama_summary = self._summarize_with_ollama(task, chunks, max_tokens)
            if ollama_summary:
                return ollama_summary
        return self.extractive_summary(chunks, max_tokens)

    @staticmethod
    def extractive_summary(chunks: list[RetrievedChunk], max_tokens: int) -> str:
        """Build a summary from exact high-signal source lines."""

        max_words = max(int(max_tokens * 0.75), 50)
        lines: list[str] = []
        for chunk in chunks:
            for line in chunk.text.splitlines():
                clean = line.strip()
                if not clean:
                    continue
                lower = clean.lower()
                if (
                    clean.startswith("#")
                    or lower.startswith(SIGNAL_PREFIXES)
                    or any(word in lower for word in SIGNAL_WORDS)
                ):
                    lines.append(f"{chunk.path}: {clean.lstrip('# ').strip()}")
                if len(lines) >= 24:
                    break
            if len(lines) >= 24:
                break
        if not lines:
            lines = [
                f"{chunk.path}: {truncate_words(chunk.text.strip(), 40)}"
                for chunk in chunks[: min(6, len(chunks))]
            ]
        return truncate_words("\n".join(dict.fromkeys(lines)), max_words)

    def summarize_session_transcript(
        self,
        transcript: str,
        title: str,
        project: str | None = None,
    ) -> dict[str, object] | None:
        """Extract structured fields from a session transcript using Ollama.

        Args:
            transcript: Raw session transcript text.
            title: Session title used as context.
            project: Optional project name for context.

        Returns:
            Dict with summary, key_takeaways, decisions, open_questions, next_actions,
            or None if Ollama is unavailable or extraction fails.
        """

        if self.config.provider != "ollama":
            return None
        excerpt = truncate_words(transcript.replace("\n", " "), 600)
        prompt = (
            "Extract structured data from this LLM session transcript.\n"
            "Respond ONLY with valid JSON matching this exact schema — no explanation, no markdown:\n"
            f"{_SESSION_EXTRACT_SCHEMA}\n\n"
            f"Rules: summary is a string; each list has 0-5 string items.\n\n"
            f"Title: {title}\n"
            f"Project: {project or 'unknown'}\n\n"
            f"Transcript:\n{excerpt}"
        )
        payload = json.dumps(
            {
                "model": self.config.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"num_predict": 512, "temperature": 0.1},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.ollama_base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            return None
        text = raw.get("response")
        if not text:
            return None
        try:
            extracted = json.loads(str(text))
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(extracted, dict):
            return None
        return {
            "summary": str(extracted.get("summary") or "").strip() or None,
            "key_takeaways": _coerce_str_list(extracted.get("key_takeaways")),
            "decisions": _coerce_str_list(extracted.get("decisions")),
            "open_questions": _coerce_str_list(extracted.get("open_questions")),
            "next_actions": _coerce_str_list(extracted.get("next_actions")),
        }

    def _summarize_with_ollama(
        self,
        task: str,
        chunks: list[RetrievedChunk],
        max_tokens: int,
    ) -> str | None:
        context = "\n\n".join(
            f"Source: {chunk.path}#{chunk.heading or ''}\n{truncate_words(chunk.text, 220)}"
            for chunk in chunks
        )
        prompt = (
            "Prepare compact cited context only. Do not solve the task.\n"
            f"Task: {task}\n\nContext:\n{context}"
        )
        payload = json.dumps(
            {
                "model": self.config.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.ollama_base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            return None
        text = raw.get("response")
        return str(text).strip() if text else None


def _coerce_str_list(value: object) -> list[str]:
    """Return a clean list of strings from an arbitrary JSON value."""

    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:5]
