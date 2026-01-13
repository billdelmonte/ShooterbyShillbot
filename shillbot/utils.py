from __future__ import annotations

import re
from typing import Optional

# Solana address regex: Base58 encoded, 32-44 characters
# Excludes 0, O, I, l to avoid confusion
SOL_ADDRESS_REGEX = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")


def extract_solana_address(text: str) -> Optional[str]:
    """
    Extract a Solana address from text.
    Looks for Base58-encoded strings between 32-44 characters.
    Returns the first match found, or None if no valid address found.
    """
    match = SOL_ADDRESS_REGEX.search(text)
    return match.group(0) if match else None
