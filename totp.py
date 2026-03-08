"""TOTP generation for Spotify authentication.

Based on https://github.com/xyloflake/spot-secrets-go/
"""
import hashlib
import hmac
import logging
import math

import requests

from librelyrics.exceptions import TOTPGenerationException

logger = logging.getLogger('librelyrics.modules.spotify.totp')

SECRET_CIPHER_DICT_URL = (
    "https://code.thetadev.de/ThetaDev/spotify-secrets/raw/branch/main/secrets/secretDict.json"
)


class TOTP:
    """TOTP generator for Spotify Web Player authentication."""
    
    def __init__(self) -> None:
        self.secret, self.version = self._get_secret_version()
        self.period = 30
        self.digits = 6

    def generate(self, timestamp: int) -> str:
        """Generate TOTP code for the given timestamp.
        
        Args:
            timestamp: Server timestamp in milliseconds.
            
        Returns:
            6-digit TOTP code.
        """
        counter = math.floor(timestamp / 1000 / self.period)
        counter_bytes = counter.to_bytes(8, byteorder="big")

        h = hmac.new(self.secret, counter_bytes, hashlib.sha1)
        hmac_result = h.digest()

        offset = hmac_result[-1] & 0x0F
        binary = (
            (hmac_result[offset] & 0x7F) << 24
            | (hmac_result[offset + 1] & 0xFF) << 16
            | (hmac_result[offset + 2] & 0xFF) << 8
            | (hmac_result[offset + 3] & 0xFF)
        )

        return str(binary % (10**self.digits)).zfill(self.digits)
    
    def _get_secret_version(self) -> tuple[bytes, str]:
        """Fetch the current secret and version from remote.
        
        Returns:
            Tuple of (secret_bytes, version_string).
            
        Raises:
            TOTPGenerationException: If secret cannot be fetched.
        """
        try:
            req = requests.get(SECRET_CIPHER_DICT_URL, timeout=10)
            if req.status_code != 200:
                raise TOTPGenerationException(
                    "Failed to fetch TOTP secret and version."
                )
            data = req.json()
            secret_version = list(data.keys())[-1]
            ascii_codes = data[secret_version]
            transformed = [val ^ ((i % 33) + 9) for i, val in enumerate(ascii_codes)]
            secret_key = "".join(str(num) for num in transformed)
            logger.debug(f"Loaded TOTP secret version: {secret_version}")
            return bytes(secret_key, 'utf-8'), secret_version
        except requests.RequestException as e:
            raise TOTPGenerationException(
                f"Failed to fetch TOTP secret: {e}"
            ) from e
