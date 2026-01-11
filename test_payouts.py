#!/usr/bin/env python3
"""
Test script for real SOL payouts on devnet.
Tests configuration, keypair setup, transfers, and verification.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from shillbot.config import load_settings
from shillbot.db import DB, connect
from shillbot.payouts import SolanaCLIPayer, lamports_to_sol, sol_to_lamports
from shillbot.solana_rpc import SolanaRPC


def test_config():
    """Test 1: Verify devnet configuration."""
    print("\n=== Test 1: Configuration ===")
    try:
        s = load_settings()
        print("OK: Config loaded successfully")
        print(f"  RPC URL: {s.rpc_url}")
        print(f"  Treasury pubkey: {s.treasury_pubkey or '(not set)'}")
        print(f"  Treasury keypair path: {s.treasury_keypair_path or '(not set)'}")
        print(f"  DRY_RUN mode: {s.dry_run}")
        
        if "devnet" not in s.rpc_url.lower():
            print("  WARNING: RPC URL does not appear to be devnet")
        
        if s.dry_run:
            print("  WARNING: DRY_RUN is true, payouts will not be sent")
        
        if not s.treasury_keypair_path:
            print("  WARNING: SHILLBOT_TREASURY_KEYPAIR_PATH not set")
        
        return s
    except Exception as e:
        print(f"FAILED: Config failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_solana_cli():
    """Test 2: Verify Solana CLI is installed and accessible."""
    print("\n=== Test 2: Solana CLI ===")
    try:
        result = subprocess.run(
            ["solana", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"OK: Solana CLI found: {version}")
            return True
        else:
            print(f"FAILED: Solana CLI returned error: {result.stderr}")
            return False
    except FileNotFoundError:
        print("FAILED: Solana CLI not found in PATH")
        print("  Install from: https://docs.solana.com/cli/install-solana-cli-tools")
        return False
    except Exception as e:
        print(f"FAILED: Error checking Solana CLI: {e}")
        return False


def get_pubkey_from_keypair(keypair_path: str) -> str | None:
    """Get public key from keypair file using Solana CLI."""
    try:
        result = subprocess.run(
            ["solana-keygen", "pubkey", keypair_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None
    except Exception:
        return None


def test_keypair_exists(s):
    """Test 3: Check if treasury keypair file exists and is readable."""
    print("\n=== Test 3: Treasury Keypair ===")
    if not s.treasury_keypair_path:
        print("SKIPPED: SHILLBOT_TREASURY_KEYPAIR_PATH not set")
        return None
    
    keypair_path = Path(s.treasury_keypair_path)
    if not keypair_path.exists():
        print(f"FAILED: Keypair file does not exist: {keypair_path}")
        print(f"  Full path: {keypair_path.absolute()}")
        return False
    
    if not keypair_path.is_file():
        print(f"FAILED: Keypair path is not a file: {keypair_path}")
        return False
    
    # Try to read pubkey from keypair
    pubkey = get_pubkey_from_keypair(str(keypair_path))
    if pubkey:
        print(f"OK: Keypair file exists and is readable")
        print(f"  Path: {keypair_path}")
        print(f"  Pubkey: {pubkey}")
        if s.treasury_pubkey and s.treasury_pubkey != pubkey:
            print(f"  WARNING: Config pubkey ({s.treasury_pubkey}) doesn't match keypair pubkey ({pubkey})")
        return True
    else:
        print(f"WARNING: Keypair file exists but could not read pubkey")
        print(f"  Path: {keypair_path}")
        return False


def test_treasury_balance(s):
    """Test 4: Check treasury wallet balance on devnet."""
    print("\n=== Test 4: Treasury Balance ===")
    if not s.treasury_pubkey:
        # Try to get pubkey from keypair
        if s.treasury_keypair_path:
            pubkey = get_pubkey_from_keypair(s.treasury_keypair_path)
            if not pubkey:
                print("SKIPPED: No treasury pubkey available (not in config, couldn't read from keypair)")
                return None
        else:
            print("SKIPPED: No treasury pubkey or keypair path configured")
            return None
    else:
        pubkey = s.treasury_pubkey
    
    try:
        rpc = SolanaRPC(url=s.rpc_url, timeout_s=20)
        balance_lamports = rpc.get_balance_lamports(pubkey)
        balance_sol = lamports_to_sol(balance_lamports)
        
        print(f"OK: Treasury balance retrieved")
        print(f"  Pubkey: {pubkey}")
        print(f"  Balance: {balance_sol:.9f} SOL ({balance_lamports} lamports)")
        
        # Check if balance is sufficient for test (at least 0.1 SOL for small transfers)
        min_balance_sol = 0.1
        if balance_sol < min_balance_sol:
            print(f"  WARNING: Balance is low (less than {min_balance_sol} SOL)")
            print(f"  Consider airdropping more SOL: solana airdrop 1 {pubkey} --url {s.rpc_url}")
        
        return True
    except Exception as e:
        print(f"FAILED: Could not retrieve balance: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_transfer_sol(s):
    """Test 5: Test a single small transfer to verify connectivity."""
    print("\n=== Test 5: Single Transfer Test ===")
    
    if s.dry_run:
        print("SKIPPED: DRY_RUN is true, skipping real transfer test")
        return None
    
    if not s.treasury_keypair_path:
        print("SKIPPED: No treasury keypair path configured")
        return None
    
    if not os.path.exists(s.treasury_keypair_path):
        print("SKIPPED: Treasury keypair file does not exist")
        return None
    
    # Use a test recipient wallet (or generate one)
    # For testing, use a known devnet wallet or create one
    test_recipient = "11111111111111111111111111111112"  # System program (safe test address)
    test_amount_sol = 0.001
    
    try:
        payer = SolanaCLIPayer(
            keypair_path=s.treasury_keypair_path,
            rpc_url=s.rpc_url,
            dry_run=False,
        )
        
        print(f"Testing transfer of {test_amount_sol} SOL to {test_recipient}...")
        status, signature = payer.transfer_sol(to_wallet=test_recipient, sol=test_amount_sol)
        
        if status == "SENT" and signature:
            print(f"OK: Transfer successful")
            print(f"  Status: {status}")
            print(f"  Signature: {signature}")
            explorer_url = f"https://explorer.solana.com/tx/{signature}?cluster=devnet"
            print(f"  Explorer: {explorer_url}")
            return True
        else:
            print(f"FAILED: Transfer returned unexpected status: {status}")
            return False
    except Exception as e:
        print(f"FAILED: Transfer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_close_with_payouts(s):
    """Test 6: Run full window close with real payouts enabled."""
    print("\n=== Test 6: Full Window Close with Real Payouts ===")
    
    if s.dry_run:
        print("SKIPPED: DRY_RUN is true, skipping real payout test")
        return None
    
    if not s.treasury_keypair_path:
        print("SKIPPED: No treasury keypair path configured")
        return None
    
    try:
        from shillbot.cli import cmd_close_once
        
        print("Running window close with real payouts...")
        print("  (This will score tweets, allocate payouts, and send real SOL transfers)")
        cmd_close_once(force=True)  # Use force to allow re-running on same window
        
        print("OK: Window close completed")
        return True
    except Exception as e:
        print(f"FAILED: Window close failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_verify_signatures(s):
    """Test 7: Verify transaction signatures are stored in database."""
    print("\n=== Test 7: Verify Signatures in Database ===")
    
    try:
        db = DB(s.db_path)
        with connect(db) as conn:
            # Get the most recent window's payouts
            rows = conn.execute(
                """
                SELECT window_id, wallet, lamports, status, signature
                FROM payouts
                ORDER BY window_id DESC
                LIMIT 10
                """
            ).fetchall()
            
            if not rows:
                print("SKIPPED: No payouts found in database")
                return None
            
            print(f"Found {len(rows)} recent payout(s)")
            all_have_signatures = True
            all_sent = True
            
            for row in rows:
                window_id = row["window_id"]
                wallet = row["wallet"]
                lamports = row["lamports"]
                status = row["status"]
                signature = row["signature"]
                
                sol_amount = lamports_to_sol(lamports)
                print(f"  Window: {window_id}, Wallet: {wallet}")
                print(f"    Amount: {sol_amount:.9f} SOL")
                print(f"    Status: {status}")
                print(f"    Signature: {signature or '(none)'}")
                
                if status != "SENT":
                    all_sent = False
                    print(f"    WARNING: Status is {status}, expected SENT")
                
                if not signature:
                    all_have_signatures = False
                    print(f"    WARNING: Missing signature")
            
            if all_sent and all_have_signatures:
                print("OK: All payouts have SENT status and signatures")
                return True
            else:
                print("FAILED: Some payouts missing signatures or incorrect status")
                return False
    except Exception as e:
        print(f"FAILED: Database verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_verify_report(s):
    """Test 8: Verify report shows real payouts with signatures."""
    print("\n=== Test 8: Verify Report ===")
    
    try:
        import json
        from pathlib import Path
        
        latest_json = Path(s.public_dir) / "latest.json"
        if not latest_json.exists():
            print("SKIPPED: latest.json not found")
            return None
        
        with open(latest_json) as f:
            report = json.load(f)
        
        print(f"Report window: {report.get('window_id', 'unknown')}")
        
        # Check payout_mode in notes
        notes = report.get("notes", [])
        payout_mode_note = [n for n in notes if "payout_mode" in n]
        if payout_mode_note:
            print(f"  {payout_mode_note[0]}")
            if "DRY_RUN" in payout_mode_note[0]:
                print("  WARNING: Report indicates DRY_RUN mode")
            elif "REAL" in payout_mode_note[0]:
                print("  OK: Report indicates REAL payout mode")
        
        # Check payouts
        payouts = report.get("payouts", [])
        if not payouts:
            print("SKIPPED: No payouts in report")
            return None
        
        print(f"Found {len(payouts)} payout(s) in report")
        all_have_signatures = True
        all_sent = True
        
        for payout in payouts:
            wallet = payout.get("wallet", "unknown")
            lamports = payout.get("lamports", 0)
            status = payout.get("status", "unknown")
            signature = payout.get("signature")
            
            sol_amount = lamports_to_sol(lamports)
            print(f"  Wallet: {wallet}")
            print(f"    Amount: {sol_amount:.9f} SOL")
            print(f"    Status: {status}")
            print(f"    Signature: {signature or '(none)'}")
            
            if status != "SENT":
                all_sent = False
            if not signature:
                all_have_signatures = False
            elif signature:
                explorer_url = f"https://explorer.solana.com/tx/{signature}?cluster=devnet"
                print(f"    Explorer: {explorer_url}")
        
        if all_sent and all_have_signatures:
            print("OK: Report shows real payouts with signatures")
            return True
        else:
            print("FAILED: Report missing signatures or incorrect status")
            return False
    except Exception as e:
        print(f"FAILED: Report verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all payout tests."""
    print("=" * 60)
    print("Real Payout Test Suite (Devnet)")
    print("=" * 60)
    
    results = {}
    
    s = test_config()
    results["config"] = s is not None
    if not s:
        print("\nCannot continue without valid config")
        sys.exit(1)
    
    results["solana_cli"] = test_solana_cli()
    results["keypair"] = test_keypair_exists(s)
    results["balance"] = test_treasury_balance(s)
    results["transfer"] = test_transfer_sol(s)
    results["close"] = test_close_with_payouts(s)
    results["signatures"] = test_verify_signatures(s)
    results["report"] = test_verify_report(s)
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, result in results.items():
        if result is None:
            status = "SKIPPED"
        elif result:
            status = "PASSED"
        else:
            status = "FAILED"
        print(f"  {test_name:20} {status}")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed > 0:
        print("\nWARNING: Some tests failed. Review output above.")
        sys.exit(1)
    elif passed > 0:
        print("\nOK: All tests that ran passed!")
    else:
        print("\nNOTE: All tests were skipped. Check configuration.")


if __name__ == "__main__":
    main()
