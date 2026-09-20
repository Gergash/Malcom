"""
Exception hierarchy for Termómetro Cultural.
Enables consistent error handling and retry decisions.
"""


class TermometroError(Exception):
    """Base exception for the application."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class TransientError(TermometroError):
    """Retryable: network, timeout, rate limit, temporary DB failure."""
    pass


class PermanentError(TermometroError):
    """Do not retry: validation, auth, not found, logic error."""
    pass


class ScraperError(TransientError):
    """Scraping failed (network, timeout, DOM change)."""
    pass


class LLMError(TransientError):
    """LLM API call failed (rate limit, timeout, service error)."""
    pass


class DatabaseError(TransientError):
    """DB operation failed (connection, deadlock)."""
    pass


class ConfigurationError(PermanentError):
    """Invalid or missing configuration."""
    pass


class ValidationError(PermanentError):
    """Invalid input or business rule violation."""
    pass
