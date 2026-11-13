from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import requests


class LLMError(RuntimeError):
    pass


class LLM(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
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
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    ) -> str:
        """
        Backward-compatible public interface.

        Existing callers can continue doing:

            llm.generate(prompt)
            llm.generate(prompt, temperature=0.0)
        """

        models = [self.model]

        for fallback in self.fallback_models:
            if fallback and fallback not in models:
                models.append(fallback)

        errors: list[str] = []

        for model in models:
            try:
                return self._generate_with_model(
                    model=model,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            except LLMError as exc:
                errors.append(f"{model}: {exc}")

        raise LLMError(
            "All configured LLM models failed:\n"
            + "\n".join(errors)
        )

    def _generate_with_model(
    self,
    model: str,
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    ) -> str:

        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }


        last_error = "Unknown error"

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
                        f"{exc}"
                    ) from exc

            # Do NOT waste retries on configuration/auth errors.
            if status in permanent_statuses:
                body = response.text[:2000]

                raise LLMError(
                    f"HTTP {status}: {body}"
                )

            last_error = (
                f"HTTP {status}: "
                f"{response.text[:2000]}"
            )

            if status not in retryable_statuses:
                raise LLMError(last_error)

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
            f"{last_error}"
        )