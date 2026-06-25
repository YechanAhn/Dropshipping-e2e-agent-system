"""
Naver API authentication helpers.

Provides two authentication strategies:

- ``NaverAuth`` -- simple header-based authentication used by the
  Naver Search API (Shopping, DataLab).  Each request carries the
  ``X-Naver-Client-Id`` / ``X-Naver-Client-Secret`` headers.

- ``NaverCommerceAuth`` -- HMAC-SHA256 signature authentication used by
  the Naver Commerce API.  Every request must include a timestamp and
  an HMAC signature derived from the HTTP method, path, and timestamp.
"""

import base64
import hashlib
import hmac
import time

from dropagent.config import NaverSearchAdSettings, NaverSettings, get_settings
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class NaverAuth:
    """
    Authentication provider for the Naver Search API (Shopping / DataLab).

    The Search APIs authenticate requests via simple header values --
    ``X-Naver-Client-Id`` and ``X-Naver-Client-Secret``.
    """

    def __init__(self, settings: NaverSettings | None = None) -> None:
        """
        Args:
            settings: Naver API credentials.  Falls back to ``get_settings().naver``.
        """
        self._settings = settings or get_settings().naver

    def get_auth_headers(self) -> dict[str, str]:
        """
        Build authentication headers for Naver Search APIs.

        Returns:
            Dictionary containing ``X-Naver-Client-Id`` and ``X-Naver-Client-Secret``.
        """
        return {
            "X-Naver-Client-Id": self._settings.client_id,
            "X-Naver-Client-Secret": self._settings.client_secret,
        }


class NaverCommerceAuth:
    """
    HMAC-SHA256 authentication provider for the Naver Commerce API.

    Each request is signed with a timestamp-based HMAC using the
    commerce client secret.  The resulting signature and metadata are
    passed via ``X-Timestamp``, ``X-API-KEY``, and ``X-HMAC-SIGNATURE``
    headers.
    """

    def __init__(self, settings: NaverSettings | None = None) -> None:
        """
        Args:
            settings: Naver API credentials.  Falls back to ``get_settings().naver``.
        """
        self._settings = settings or get_settings().naver

    @staticmethod
    def _get_timestamp() -> str:
        """Return the current UNIX timestamp in milliseconds as a string."""
        return str(int(time.time() * 1000))

    def generate_signature(self, timestamp: str, method: str, path: str) -> str:
        """
        Generate a Base64-encoded HMAC-SHA256 signature.

        The signature is computed over the concatenation of
        ``{path}\\n{timestamp}\\n{method}`` using the commerce client
        secret as the HMAC key.

        Args:
            timestamp: UNIX timestamp in milliseconds (string).
            method: HTTP method (e.g. ``GET``, ``POST``).
            path: API endpoint path (e.g. ``/v2/products``).

        Returns:
            Base64-encoded HMAC-SHA256 signature string.
        """
        # Naver Commerce API sign string: path + \n + timestamp + \n + method
        message = f"{path}\n{timestamp}\n{method}"
        signature = hmac.new(
            self._settings.commerce_client_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def get_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """
        Build the full set of authentication headers for a Commerce API request.

        Args:
            method: HTTP method (uppercase, e.g. ``POST``).
            path: API endpoint path (e.g. ``/v2/products``).

        Returns:
            Dictionary with ``X-Timestamp``, ``X-API-KEY``, and
            ``X-HMAC-SIGNATURE`` headers.
        """
        timestamp = self._get_timestamp()
        signature = self.generate_signature(timestamp, method, path)

        return {
            "X-Timestamp": timestamp,
            "X-API-KEY": self._settings.commerce_client_id,
            "X-HMAC-SIGNATURE": signature,
        }


class NaverSearchAdAuth:
    """
    HMAC-SHA256 authentication provider for the Naver Search Ad (검색광고) API.

    The Search Ad API signs every request over ``{timestamp}.{method}.{uri}``
    (note: only the path, no query string) using the account secret key, and
    passes the signature plus the access-license key and customer id via the
    ``X-Timestamp`` / ``X-API-KEY`` / ``X-Customer`` / ``X-Signature`` headers.

    Reference:
        https://naver.github.io/searchad-apidoc/  (signaturehelper)
    """

    def __init__(self, settings: NaverSearchAdSettings | None = None) -> None:
        """
        Args:
            settings: Search Ad credentials. Falls back to ``get_settings().searchad``.
        """
        self._settings = settings or get_settings().searchad

    @staticmethod
    def _get_timestamp() -> str:
        """Return the current UNIX timestamp in milliseconds as a string."""
        return str(int(time.time() * 1000))

    def generate_signature(self, timestamp: str, method: str, uri: str) -> str:
        """
        Generate a Base64-encoded HMAC-SHA256 signature.

        The signature is computed over ``{timestamp}.{method}.{uri}`` using the
        Search Ad secret key as the HMAC key. ``method`` must be uppercase and
        ``uri`` is the path only (e.g. ``/keywordstool``), excluding the query.

        Args:
            timestamp: UNIX timestamp in milliseconds (string).
            method: HTTP method (e.g. ``GET``).
            uri: API path (e.g. ``/keywordstool``).

        Returns:
            Base64-encoded HMAC-SHA256 signature string.
        """
        message = f"{timestamp}.{method.upper()}.{uri}"
        signature = hmac.new(
            self._settings.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def get_auth_headers(self, method: str, uri: str) -> dict[str, str]:
        """
        Build the full set of authentication headers for a Search Ad request.

        Args:
            method: HTTP method (e.g. ``GET``).
            uri: API path (e.g. ``/keywordstool``), excluding any query string.

        Returns:
            Dictionary with ``X-Timestamp``, ``X-API-KEY``, ``X-Customer``,
            and ``X-Signature`` headers.
        """
        timestamp = self._get_timestamp()
        signature = self.generate_signature(timestamp, method, uri)

        return {
            "X-Timestamp": timestamp,
            "X-API-KEY": self._settings.api_key,
            "X-Customer": str(self._settings.customer_id),
            "X-Signature": signature,
        }
