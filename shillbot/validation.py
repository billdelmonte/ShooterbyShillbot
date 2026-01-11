from __future__ import annotations

import re
from typing import Optional

# Solana pubkey is Base58 encoded, 32-44 characters
# Base58 alphabet: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
_SOLANA_PUBKEY_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_valid_solana_pubkey(address: str) -> bool:
    """
    Validate Solana pubkey format.
    Solana addresses are Base58 encoded and typically 32-44 characters.
    """
    if not address or not isinstance(address, str):
        return False
    address = address.strip()
    return bool(_SOLANA_PUBKEY_PATTERN.match(address))


def extract_solana_pubkey(text: str) -> Optional[str]:
    """
    Extract Solana pubkey from text.
    Looks for Base58-encoded strings that match Solana address format.
    """
    # Try to find a valid-looking Solana address in the text
    words = text.split()
    for word in words:
        # Remove common punctuation
        cleaned = word.strip(".,;:!?()[]{}")
        if is_valid_solana_pubkey(cleaned):
            return cleaned
    return None
