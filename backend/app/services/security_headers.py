from starlette.responses import Response

SECURITY_HEADERS = {
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


def apply_security_headers(response: Response) -> Response:
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    return response
