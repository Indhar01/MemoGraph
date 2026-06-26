"""RFC 7636 Proof Key for Code Exchange.

PKCE is mandatory for the public OAuth clients we operate
(operator-supplied client_id with no client_secret in BYOC mode) and
strongly recommended even when a client_secret is present. The flow:

1. Client generates a high-entropy ``code_verifier`` (43-128 chars).
2. Client computes ``code_challenge = base64url(sha256(verifier))``.
3. Client sends ``code_challenge`` + ``code_challenge_method=S256``
   in the authorization request.
4. After the user consents and the AS redirects with ``code``,
   client exchanges ``code + code_verifier`` for tokens. The AS
   verifies SHA-256(verifier) matches the previously stored
   challenge — proves the redeemer is the same party that started
   the flow.

The verifier MUST be kept server-side between the start and
callback handlers; we stash it on the ``state`` parameter via the
:class:`PKCEChallenge` dataclass below and persist the binding in
the OAuth start route.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass


# Per RFC 7636 §4.1: verifier is 43-128 chars from [A-Z][a-z][0-9]-._~
# We use ``secrets.token_urlsafe`` which returns base64url without
# padding — within the allowed alphabet. 64 bytes → 86 chars after
# encoding, well inside the 43-128 range.
_VERIFIER_BYTES = 64


@dataclass(frozen=True)
class PKCEChallenge:
    """A verifier + its matching challenge, ready for the OAuth flow.

    Carry the ``verifier`` server-side until the callback fires;
    send ``challenge`` and ``method`` in the authorization URL.
    """

    verifier: str
    challenge: str
    method: str = "S256"


def new_pkce_challenge() -> PKCEChallenge:
    """Generate a fresh PKCE verifier + S256 challenge.

    Returns a new :class:`PKCEChallenge` every call — never reuse a
    verifier across flows. Test code that needs determinism should
    construct :class:`PKCEChallenge` directly rather than seed
    ``secrets``.
    """
    verifier = secrets.token_urlsafe(_VERIFIER_BYTES)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEChallenge(verifier=verifier, challenge=challenge)


__all__ = ["PKCEChallenge", "new_pkce_challenge"]
