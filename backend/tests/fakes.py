"""Small fakes shared by the AI-layer tests."""

from types import SimpleNamespace


class FakeHTTPError(Exception):
    """Looks like a groq/openai API error: has `status_code` and `response.headers`."""

    def __init__(
        self, status_code: int, headers: dict[str, str] | None = None, message: str = ""
    ) -> None:
        super().__init__(f"HTTP {status_code} {message}".strip())
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})
