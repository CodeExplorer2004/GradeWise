from starlette.responses import Response

from app.services.security_headers import SECURITY_HEADERS, apply_security_headers


def test_security_headers_cover_framing_sniffing_referrer_and_browser_permissions() -> None:
    response = apply_security_headers(Response())

    assert {name: response.headers[name] for name in SECURITY_HEADERS} == {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "form-action 'self'"
        ),
    }


def test_security_headers_preserve_unrelated_response_metadata() -> None:
    response = Response(headers={"X-Request-ID": "trace-123"})

    apply_security_headers(response)

    assert response.headers["X-Request-ID"] == "trace-123"
