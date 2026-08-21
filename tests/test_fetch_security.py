from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_article  # noqa: E402  (the script directory is added above)


PUBLIC_IPV4_RESULT = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 80))
]


class FakeHTTPResponse:
    """Small stand-in that records bounded reads from an HTTP response."""

    def __init__(
        self,
        *,
        status: int = 200,
        reason: str = "OK",
        body: bytes = b"<html><title>Public page</title><body>Useful content</body></html>",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.reason = reason
        self.body = body
        self.read_sizes: list[int | None] = []
        self.headers = Message()
        for name, value in (headers or {"Content-Type": "text/html; charset=utf-8"}).items():
            self.headers[name] = value

    def read(self, amount: int | None = None) -> bytes:
        self.read_sizes.append(amount)
        return self.body if amount is None else self.body[:amount]

    def close(self) -> None:
        return None


def fake_connection_class(response: FakeHTTPResponse):
    """Build a connection double while preserving the pinned-IP constructor."""

    class FakeConnection:
        instances: list[FakeConnection] = []

        def __init__(
            self,
            host: str,
            connect_ips: tuple[str, ...],
            port: int,
            timeout: int,
        ) -> None:
            self.host = host
            self.connect_ips = connect_ips
            self.port = port
            self.timeout = timeout
            self.request_target: str | None = None
            self.__class__.instances.append(self)

        def request(self, method: str, target: str, headers: dict[str, str]) -> None:
            self.request_target = target

        def getresponse(self) -> FakeHTTPResponse:
            return response

        def close(self) -> None:
            return None

    return FakeConnection


class SafeFetchTests(unittest.TestCase):
    def test_connection_falls_back_across_validated_public_ips(self) -> None:
        """A failed IPv6/public address must not prevent a working fallback."""

        expected_socket = object()
        connection = mock.Mock()
        connection.port = 443
        connection.timeout = 20
        connection.source_address = None
        connection._create_connection.side_effect = [OSError("unreachable"), expected_socket]

        connected_socket = fetch_article._connect_to_validated_ip(
            connection,
            ("2001:4860:4860::8888", "93.184.216.34"),
        )

        self.assertIs(connected_socket, expected_socket)
        self.assertEqual(connection._create_connection.call_count, 2)

    def test_direct_file_url_is_rejected(self) -> None:
        """A bookmark URL must never turn into a local-file read."""

        with tempfile.NamedTemporaryFile() as secret_file:
            secret_file.write(b"local-secret")
            secret_file.flush()

            result = fetch_article.fetch_readable_url(Path(secret_file.name).as_uri())

        self.assertFalse(result.ok)
        self.assertIn("scheme", result.error or "")
        self.assertNotIn("local-secret", result.content or "")

    def test_direct_loopback_url_is_rejected_before_connecting(self) -> None:
        """Non-public IPv4 and IPv6 literals are blocked before connection."""

        unsafe_urls = (
            "http://127.0.0.1:9/admin",
            "http://10.0.0.8/admin",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/admin",
            "http://[fc00::1]/admin",
            "http://[::ffff:127.0.0.1]/admin",
        )
        for unsafe_url in unsafe_urls:
            with self.subTest(url=unsafe_url):
                result = fetch_article.fetch_readable_url(unsafe_url)
                self.assertFalse(result.ok)
                self.assertIn("non-public", result.error or "")

    def test_hostname_resolving_to_private_ip_is_rejected(self) -> None:
        """Checking only the hostname text is insufficient; DNS answers matter."""

        private_result = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", 80))
        ]
        with mock.patch("socket.getaddrinfo", return_value=private_result):
            result = fetch_article.fetch_readable_url("http://attacker.example/private")

        self.assertFalse(result.ok)
        self.assertIn("non-public", result.error or "")

    def test_mixed_public_and_private_dns_answers_are_rejected(self) -> None:
        """A hostname is unsafe if any answer could route to a private host."""

        mixed_results = [
            *PUBLIC_IPV4_RESULT,
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.20", 80)),
        ]
        with mock.patch("socket.getaddrinfo", return_value=mixed_results):
            result = fetch_article.fetch_readable_url("http://mixed.example/article")

        self.assertFalse(result.ok)
        self.assertIn("non-public", result.error or "")

    def test_redirect_target_is_validated_again(self) -> None:
        """A public first hop must not redirect the fetcher into localhost."""

        redirect_response = FakeHTTPResponse(
            status=302,
            reason="Found",
            body=b"",
            headers={"Location": "http://127.0.0.1/internal"},
        )
        fake_connection = fake_connection_class(redirect_response)
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_IPV4_RESULT),
            mock.patch.object(fetch_article, "_PinnedHTTPConnection", fake_connection),
        ):
            result = fetch_article.fetch_readable_url("http://attacker.example/start")

        self.assertFalse(result.ok)
        self.assertIn("non-public", result.error or "")
        self.assertEqual(len(fake_connection.instances), 1)

    def test_response_body_is_bounded_before_decoding(self) -> None:
        """The network read itself is capped, not only the resulting string."""

        oversized_response = FakeHTTPResponse(body=b"123456789")
        fake_connection = fake_connection_class(oversized_response)
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_IPV4_RESULT),
            mock.patch.object(fetch_article, "_PinnedHTTPConnection", fake_connection),
        ):
            result = fetch_article.fetch_readable_url(
                "http://public.example/large",
                max_response_bytes=8,
            )

        self.assertFalse(result.ok)
        self.assertIn("maximum size", result.error or "")
        self.assertEqual(oversized_response.read_sizes, [9])

    def test_declared_oversized_body_is_rejected_without_reading(self) -> None:
        """An excessive Content-Length is rejected before body bytes are read."""

        oversized_response = FakeHTTPResponse(
            body=b"small test body",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Length": "999",
            },
        )
        fake_connection = fake_connection_class(oversized_response)
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_IPV4_RESULT),
            mock.patch.object(fetch_article, "_PinnedHTTPConnection", fake_connection),
        ):
            result = fetch_article.fetch_readable_url(
                "http://public.example/large",
                max_response_bytes=8,
            )

        self.assertFalse(result.ok)
        self.assertIn("maximum size", result.error or "")
        self.assertEqual(oversized_response.read_sizes, [])

    def test_public_http_page_remains_supported(self) -> None:
        """The security guard must preserve the normal public-web workflow."""

        public_response = FakeHTTPResponse()
        fake_connection = fake_connection_class(public_response)
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_IPV4_RESULT),
            mock.patch.object(fetch_article, "_PinnedHTTPConnection", fake_connection),
        ):
            result = fetch_article.fetch_readable_url("http://public.example/article")

        self.assertTrue(result.ok)
        self.assertEqual(result.title, "Public page")
        self.assertIn("Useful content", result.content or "")
        self.assertEqual(fake_connection.instances[0].connect_ips, ("93.184.216.34",))
        self.assertEqual(fake_connection.instances[0].request_target, "/article")

    def test_public_https_page_uses_original_hostname_and_pinned_ip(self) -> None:
        """HTTPS keeps normal hostname verification while pinning the address."""

        public_response = FakeHTTPResponse()
        fake_connection = fake_connection_class(public_response)
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_IPV4_RESULT),
            mock.patch.object(fetch_article, "_PinnedHTTPSConnection", fake_connection),
        ):
            result = fetch_article.fetch_readable_url("https://public.example/article")

        self.assertTrue(result.ok)
        self.assertEqual(fake_connection.instances[0].host, "public.example")
        self.assertEqual(fake_connection.instances[0].connect_ips, ("93.184.216.34",))
        self.assertEqual(fake_connection.instances[0].port, 443)

    def test_redirect_to_ftp_is_rejected(self) -> None:
        """Redirect handling must not re-enable urllib's FTP support."""

        redirect_response = FakeHTTPResponse(
            status=302,
            reason="Found",
            body=b"",
            headers={"Location": "ftp://public.example/archive"},
        )
        fake_connection = fake_connection_class(redirect_response)
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_IPV4_RESULT),
            mock.patch.object(fetch_article, "_PinnedHTTPConnection", fake_connection),
        ):
            result = fetch_article.fetch_readable_url("http://attacker.example/start")

        self.assertFalse(result.ok)
        self.assertIn("scheme", result.error or "")


if __name__ == "__main__":
    unittest.main()
