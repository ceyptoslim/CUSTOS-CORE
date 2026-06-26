"""
CUSTOS Input Validation

Pre-flight validation layer that runs before policy evaluation.
Catches malformed, oversized, or structurally invalid input
before it reaches the policy engine.

Validation failures return structured errors, not 500s.
"""

from dataclasses import dataclass
from typing import Optional


MAX_CONTENT_BYTES = 32_768   # 32 KB hard limit
MAX_CLIENT_ID_LEN = 128
ALLOWED_OPERATIONS = {"evaluate", "classify", "audit"}   # extensible


@dataclass
class ValidationResult:
    valid: bool
    error: Optional[str] = None


class InputValidator:
    """
    Stateless validator. All methods are pure functions with no side effects.
    Instantiate once and reuse across requests.
    """

    def validate_content(self, content: str) -> ValidationResult:
        """Validate raw content string before policy evaluation."""
        if not isinstance(content, str):
            return ValidationResult(False, "content must be a string")

        if not content or not content.strip():
            return ValidationResult(False, "content must not be empty or blank")

        byte_size = len(content.encode("utf-8"))
        if byte_size > MAX_CONTENT_BYTES:
            return ValidationResult(
                False,
                f"content exceeds maximum size of {MAX_CONTENT_BYTES} bytes "
                f"(received {byte_size} bytes)",
            )

        return ValidationResult(True)

    def validate_client_id(self, client_id: str) -> ValidationResult:
        """Validate client identifier format."""
        if not isinstance(client_id, str):
            return ValidationResult(False, "client_id must be a string")

        if not client_id or not client_id.strip():
            return ValidationResult(False, "client_id must not be empty or blank")

        if len(client_id) > MAX_CLIENT_ID_LEN:
            return ValidationResult(
                False,
                f"client_id exceeds maximum length of {MAX_CLIENT_ID_LEN} characters",
            )

        if client_id != client_id.strip():
            return ValidationResult(
                False, "client_id must not have leading or trailing whitespace"
            )

        return ValidationResult(True)

    def validate_token_count(self, token_count: int) -> ValidationResult:
        """Validate token count is a positive integer within bounds."""
        if not isinstance(token_count, int) or isinstance(token_count, bool):
            return ValidationResult(False, "token_count must be an integer")

        if token_count < 1:
            return ValidationResult(False, "token_count must be at least 1")

        if token_count > 100_000:
            return ValidationResult(
                False, "token_count must not exceed 100,000 per request"
            )

        return ValidationResult(True)

    def validate_request(
        self,
        client_id: str,
        content: str,
        token_count: int = 1,
    ) -> ValidationResult:
        """
        Full request validation in one call.
        Returns the first failure found, or valid if all pass.
        """
        for result in [
            self.validate_client_id(client_id),
            self.validate_content(content),
            self.validate_token_count(token_count),
        ]:
            if not result.valid:
                return result

        return ValidationResult(True)
