import json
import os
import re
import time
from typing import Any

from openai import OpenAI


class PermanentAPIError(Exception):
    """Raised when an API error is permanent (e.g., 400, 401, 404) and should not be retried."""
    pass


class OmnirouteClient:

    def _parse_json_response(self, content: str | None) -> dict[str, Any]:
        if content is None:
            raise ValueError("AI response content is None (possible refusal or tool-call response)")
        # strip markdown code blocks from start/end
        content = content.strip()
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        content = content.strip()
        # extract first JSON object or array if surrounded by prose
        match = re.search(r'(\{.*\}|\[.*\])', content, re.DOTALL)
        if match:
            content = match.group(1)
        return json.loads(content)

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        max_retries: int = 3,
        timeout: int = 300,
    ):
        self.base_url = base_url or os.getenv(
            "OMNIROUTE_BASE_URL", "http://localhost:20128/v1"
        )
        self.api_key = api_key or os.getenv(
            "OMNIROUTE_API_KEY", "sk-f0c1ddf471008e76-f92ijk-07d16379"
        )
        self.max_retries = max_retries
        self.timeout = timeout
        self.client = OpenAI(
            base_url=self.base_url, api_key=self.api_key, timeout=self.timeout
        )
        self._supports_images: bool | None = None

    def generate_text(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        model: str = "auto/best-chat",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response.choices[0].message.content
            except Exception as e:
                err_str = str(e).lower()
                # Permanent errors: do not retry
                if any(code in err_str for code in ("400", "401", "403", "404", "invalid_request")):
                    raise PermanentAPIError(f"Permanent API error: {e}") from e
                if attempt == self.max_retries - 1:
                    raise
                wait_time = (2**attempt) + 0.1
                time.sleep(wait_time)
        return ""

    def generate_structured(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        response_schema: dict[str, Any] | None = None,
        model: str = "auto/best-chat",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        if response_schema:
            system_prompt += (
                f"\n\nRespond with valid JSON matching this schema: {response_schema}"
            )

        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": prompt + "\n\nRespond with JSON only.",
                        },
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = response.choices[0].message.content
                return self._parse_json_response(content)
            except (json.JSONDecodeError, ValueError):
                raise  # permanent — do not retry
            except Exception as e:
                err_str = str(e).lower()
                # Permanent errors: do not retry
                if any(code in err_str for code in ("400", "401", "403", "404", "invalid_request")):
                    raise PermanentAPIError(f"Permanent API error: {e}") from e
                if attempt == self.max_retries - 1:
                    raise
                wait_time = (2**attempt) + 0.1
                time.sleep(wait_time)
        return {}

    def generate_image(self, prompt: str, size: str = "1024x1024", model: str = "dall-e-3") -> bytes:
        """Generate an image. Raises RuntimeError if proxy does not support images."""
        if self._supports_images is False:
            raise RuntimeError("Image generation not supported by this OmniRoute proxy")
        import base64
        try:
            response = self.client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                response_format="b64_json",
                n=1,
            )
            self._supports_images = True
            return base64.b64decode(response.data[0].b64_json)
        except Exception as e:
            err_str = str(e).lower()
            type_name = type(e).__name__
            if "404" in err_str or "not found" in err_str or type_name in ("NotFoundError", "APIStatusError"):
                self._supports_images = False
            raise RuntimeError(f"Image generation unavailable: {e}") from e
