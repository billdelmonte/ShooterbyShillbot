from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class SolanaCLIPayer:
    """Execute Solana transfers using the Solana CLI."""
    
    keypair_path: str
    rpc_url: str

    def transfer_sol(self, to_wallet: str, sol: float) -> Tuple[str, Optional[str]]:
        """
        Transfer SOL to a wallet using solana CLI.
        
        Args:
            to_wallet: Recipient wallet address
            sol: Amount of SOL to transfer
            
        Returns:
            Tuple of (status, tx_signature)
            - status: "SENT" on success, "FAILED" on failure
            - tx_signature: Transaction signature if successful, None otherwise
        """
        cmd = [
            "solana",
            "transfer",
            to_wallet,
            str(sol),
            "--keypair",
            self.keypair_path,
            "--url",
            self.rpc_url,
            "--allow-unfunded-recipient",
        ]
        
        proc = subprocess.run(cmd, capture_output=True, text=True)
        
        if proc.returncode != 0:
            error_msg = f"solana transfer failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            raise RuntimeError(error_msg)

        # Extract transaction signature from output
        tx_signature = None
        for line in proc.stdout.splitlines():
            if "Signature:" in line:
                tx_signature = line.split("Signature:", 1)[1].strip()
                break
        
        if tx_signature:
            return ("SENT", tx_signature)
        else:
            return ("FAILED", None)
