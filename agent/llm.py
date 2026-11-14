from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import requests


def error_line(
    status: int | None,
    detail: str,
    kind: str = "http",
) -> str:
    """One readable line from structured failure data.

    ``status`` is the HTTP code when a response arrived, ``detail`` is the
    provider's own message, and ``kind`` says whether the request reached
    the provider at all. Panels and command output share this so the
    wording cannot drift apart from the fields.
    """

    text = " ".join(str(detail).split())

    if status is not None:
        return f"HTTP {status}: {text}" if text else f"HTTP {status}"

    if kind == "network":
        return f"network error: {text}" if text else "network error"

    return text or "no response"


class LLMError(RuntimeError):
    """A failed model call, carrying what a panel needs to explain it.

    The message text stays human-readable for logs; ``status``, ``detail``
    and ``kind`` are the machine-readable facts, so callers never have to
    parse the message.
    """

    def __init__(
        self,
        message: str,
        status: int | None = None,
        detail: str = "",
        kind: str = "http",
    ) -> None:
        super().__init__(message)

        self.status = status
        self.detail = detail
        self.kind = kind

    @property
    def reason(self) -> str:
        """The short line for a one-line status, e.g. "HTTP 401: ..."."""

        return error_line(self.status, self.detail, self.kind)


class LLM(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str | list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        raise NotImplementedError


class OpenAICompatibleLLM(LLM):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 120,
        fallback_models: list[str] | None = None,
        max_attempts: int = 3,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 4.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

        self.fallback_models = fallback_models or []

        self.max_attempts = max(1, max_attempts)
        self.retry_base_seconds = max(0.0, retry_base_seconds)
        self.retry_max_seconds = max(
            self.retry_base_seconds,
            retry_max_seconds,
        )

    def generate(
        self,
        prompt: str | list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """
        Accept either a plain prompt string or a chat message list.

        Both of these work:

            llm.generate("Summarise this")
            llm.generate([{"role": "system", "content": ...}, ...])
        """

        messages = (
            [{"role": "user", "content": prompt}]
            if isinstance(prompt, str)
            else list(prompt)
        )

        models = [self.model]

        for fallback in self.fallback_models:
            if fallback and fallback not in models:
                models.append(fallback)

        errors: list[str] = []
        failures: list[LLMError] = []

        for model in models:
            try:
                return self._generate_with_model(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            except LLMError as exc:
                errors.append(f"{model}: {exc}")
                failures.append(exc)

        first = failures[0]

        raise LLMError(
            "All configured LLM models failed:\n"
            + "\n".join(errors),
            status=first.status,
            detail=first.detail,
            kind=first.kind,
        )

    def _generate_with_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:

        url = f"{self.base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
        }

        # Local servers (Ollama, LM Studio, llama.cpp) need no credentials.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens


        last_error = "Unknown error"
        last_status: int | None = None
        last_detail = ""
        last_kind = "http"

        retryable_statuses = {
            408,
            429,
            500,
            502,
            503,
            504,
        }

        permanent_statuses = {
            400,
            401,
            402,
            403,
            404,
        }

        for attempt in range(1, self.max_attempts + 1):

            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

            except requests.RequestException as exc:
                last_error = (
                    f"network error: {exc}"
                )
                last_status = None
                last_detail = str(exc)
                last_kind = "network"

                if attempt >= self.max_attempts:
                    break

                delay = min(
                    self.retry_base_seconds
                    * (2 ** (attempt - 1)),
                    self.retry_max_seconds,
                )

                print(
                    f"LLM {model}: network error on "
                    f"attempt {attempt}/{self.max_attempts}; "
                    f"retrying in {delay:.1f}s"
                )

                time.sleep(delay)
                continue

            status = response.status_code

            if status == 200:
                try:
                    data = response.json()

                    content = (
                        data["choices"][0]["message"]["content"]
                    )

                    if not content:
                        raise ValueError(
                            "Empty model response"
                        )

                    return content

                except Exception as exc:
                    raise LLMError(
                        f"{model}: invalid successful response: "
                        f"{exc}",
                        detail=str(exc),
                        kind="response",
                    ) from exc

            # Do NOT waste retries on configuration/auth errors.
            if status in permanent_statuses:
                body = response.text[:2000]

                raise LLMError(
                    f"HTTP {status}: {body}",
                    status=status,
                    detail=body,
                )

            last_status = status
            last_detail = response.text[:2000]
            last_kind = "http"

            last_error = f"HTTP {status}: {last_detail}"

            if status not in retryable_statuses:
                raise LLMError(
                    last_error,
                    status=status,
                    detail=last_detail,
                )

            if attempt >= self.max_attempts:
                break

            delay = min(
                self.retry_base_seconds
                * (2 ** (attempt - 1)),
                self.retry_max_seconds,
            )

            print(
                f"LLM {model}: HTTP {status} on "
                f"attempt {attempt}/{self.max_attempts}; "
                f"retrying in {delay:.1f}s"
            )

            time.sleep(delay)

        raise LLMError(
            f"{model} failed after "
            f"{self.max_attempts} attempts: "
            f"{last_error}",
            status=last_status,
            detail=last_detail,
            kind=last_kind,
        )