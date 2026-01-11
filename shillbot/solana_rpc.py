from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SolanaRPC:
    url: str
    timeout_s: int = 20

    def get_balance_lamports(self, pubkey: str) -> int:
        """
        Read SOL balance (in lamports) for a given pubkey using Solana JSON-RPC.
        Raises RuntimeError if RPC call fails.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if "error" in result:
                    raise RuntimeError(f"Solana RPC error: {result['error']}")
                if "result" not in result:
                    raise RuntimeError(f"Solana RPC missing result: {result}")
                balance = result["result"].get("value")
                if balance is None:
                    raise RuntimeError(f"Solana RPC missing balance value: {result['result']}")
                return int(balance)
        except urllib.error.URLError as e:
            raise RuntimeError(f"Solana RPC request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Solana RPC invalid JSON response: {e}") from e

    def get_token_balance(self, wallet_pubkey: str, token_mint: str) -> int:
        """
        Get SPL token balance for a wallet and token mint.
        Returns token balance in token's native units (not lamports).
        Returns 0 if wallet doesn't hold the token.
        Raises RuntimeError if RPC call fails.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_pubkey,
                {"mint": token_mint},
                {"encoding": "jsonParsed"}
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if "error" in result:
                    raise RuntimeError(f"Solana RPC error: {result['error']}")
                if "result" not in result:
                    raise RuntimeError(f"Solana RPC missing result: {result}")
                
                accounts = result["result"].get("value", [])
                if not accounts:
                    # Wallet doesn't hold this token
                    return 0
                
                # Get balance from first account (there should only be one per mint per wallet)
                account_data = accounts[0].get("account", {}).get("data", {})
                parsed = account_data.get("parsed", {})
                info = parsed.get("info", {})
                token_amount = info.get("tokenAmount", {})
                amount_str = token_amount.get("amount", "0")
                
                return int(amount_str)
        except urllib.error.URLError as e:
            raise RuntimeError(f"Solana RPC request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Solana RPC invalid JSON response: {e}") from e
        except (KeyError, ValueError, TypeError) as e:
            raise RuntimeError(f"Solana RPC invalid response format: {e}") from e
