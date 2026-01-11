#!/usr/bin/env python3
"""
Manual test script for X/Twitter ingest functionality.
Tests registration parsing, shill collection, rate limiting, and CSV export.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from shillbot.config import load_settings
from shillbot.db import DB, connect, init_db
from shillbot.models import Tweet
from shillbot.rate_limit import apply_rate_limit
from shillbot.validation import extract_solana_pubkey, is_valid_solana_pubkey
from shillbot.x_ingest import XIngestor
from shillbot.scrapingdog import ScrapingDogClient


def test_config():
    """Test 1: Verify configuration loads correctly."""
    print("\n=== Test 1: Configuration ===")
    try:
        s = load_settings()
        print(f"✓ Config loaded successfully")
        print(f"  API Key set: {bool(s.scrapingdog_api_key)}")
        print(f"  Coin handle: {s.coin_handle}")
        print(f"  Coin ticker: {s.coin_ticker}")
        print(f"  Register hashtag: {s.register_hashtag}")
        return s
    except Exception as e:
        print(f"✗ Config failed: {e}")
        return None


def test_validation():
    """Test 2: Validate Solana pubkey validation."""
    print("\n=== Test 2: Validation ===")
    valid_address = "C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD"
    invalid_address = "invalid_address"
    
    try:
        assert is_valid_solana_pubkey(valid_address), "Valid address should pass"
        assert not is_valid_solana_pubkey(invalid_address), "Invalid address should fail"
        
        # Test extraction
        text = "#Shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD"
        extracted = extract_solana_pubkey(text)
        assert extracted == valid_address, "Should extract valid address"
        
        print("✓ Validation tests passed")
        return True
    except AssertionError as e:
        print(f"✗ Validation test failed: {e}")
        return False


def test_registration_parsing(s: any):
    """Test 3: Test registration hashtag parsing."""
    print("\n=== Test 3: Registration Parsing ===")
    try:
        client = ScrapingDogClient(api_key=s.scrapingdog_api_key or "test", timeout_s=30)
        ingestor = XIngestor(
            client=client,
            handle=s.handle,
            dynamic=s.scrapingdog_dynamic,
            coin_handle=s.coin_handle,
            coin_ticker=s.coin_ticker,
            token_mint=s.token_mint if s.token_mint else None,
            register_hashtag=s.register_hashtag,
        )
        
        test_cases = [
            ("#Shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", True),
            ("#shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", True),  # Case insensitive
            ("Check out #Shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", True),
            ("#Shillbot-register invalid", False),
            ("No hashtag here", False),
        ]
        
        passed = 0
        for text, should_find in test_cases:
            wallet = ingestor.parse_registration_hashtag(text)
            found = wallet is not None
            if found == should_find:
                passed += 1
                status = "✓" if found else "✓ (correctly rejected)"
                print(f"  {status} '{text[:50]}...' -> {wallet}")
            else:
                print(f"  ✗ '{text[:50]}...' -> Expected {should_find}, got {found}")
        
        print(f"✓ Registration parsing: {passed}/{len(test_cases)} tests passed")
        return passed == len(test_cases)
    except Exception as e:
        print(f"✗ Registration parsing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiting():
    """Test 4: Test rate limiting logic."""
    print("\n=== Test 4: Rate Limiting ===")
    try:
        # Test: Same user, same minute (should keep first)
        base_time = "2026-01-10T14:23:00+00:00"
        tweets = [
            Tweet("t1", "user1", "2026-01-10T14:23:10+00:00", "text1", 0, 0, 0, 0, 0, False, ""),
            Tweet("t2", "user1", "2026-01-10T14:23:45+00:00", "text2", 0, 0, 0, 0, 0, False, ""),
            Tweet("t3", "user1", "2026-01-10T14:24:10+00:00", "text3", 0, 0, 0, 0, 0, False, ""),
        ]
        filtered = apply_rate_limit(tweets)
        assert len(filtered) == 2, f"Should keep 2 (one per minute), got {len(filtered)}"
        assert filtered[0].tweet_id == "t1", "Should keep first tweet in minute"
        print("  ✓ Same user, same minute: keeps first per minute")
        
        # Test: Different users, same minute (should keep both)
        tweets2 = [
            Tweet("t1", "user1", "2026-01-10T14:23:10+00:00", "text1", 0, 0, 0, 0, 0, False, ""),
            Tweet("t2", "user2", "2026-01-10T14:23:20+00:00", "text2", 0, 0, 0, 0, 0, False, ""),
        ]
        filtered2 = apply_rate_limit(tweets2)
        assert len(filtered2) == 2, f"Should keep both users, got {len(filtered2)}"
        print("  ✓ Different users, same minute: keeps both")
        
        # Test: Same user, different minutes (should keep all)
        tweets3 = [
            Tweet("t1", "user1", "2026-01-10T14:23:10+00:00", "text1", 0, 0, 0, 0, 0, False, ""),
            Tweet("t2", "user1", "2026-01-10T14:24:10+00:00", "text2", 0, 0, 0, 0, 0, False, ""),
            Tweet("t3", "user1", "2026-01-10T14:25:10+00:00", "text3", 0, 0, 0, 0, 0, False, ""),
        ]
        filtered3 = apply_rate_limit(tweets3)
        assert len(filtered3) == 3, f"Should keep all (different minutes), got {len(filtered3)}"
        print("  ✓ Same user, different minutes: keeps all")
        
        print("✓ Rate limiting tests passed")
        return True
    except AssertionError as e:
        print(f"✗ Rate limiting test failed: {e}")
        return False


def test_database_schema():
    """Test 5: Verify database schema."""
    print("\n=== Test 5: Database Schema ===")
    try:
        s = load_settings()
        db = DB(s.db_path)
        
        # First, ensure DB is initialized
        try:
            init_db(db)
        except Exception:
            pass  # Might already be initialized
        
        with connect(db) as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            
            required_tables = ["registrations", "shills", "interim_shills", "windows", "scores", "payouts"]
            missing = [t for t in required_tables if t not in tables]
            
            if missing:
                print(f"✗ Missing tables: {missing}")
                print("  Try running: python -m shillbot init-db")
                return False
            
            # Check interim_shills structure
            cols = [row[1] for row in conn.execute("PRAGMA table_info(interim_shills)").fetchall()]
            required_cols = ["tweet_id", "handle", "created_at_utc", "pulled_at_utc"]
            missing_cols = [c for c in required_cols if c not in cols]
            
            if missing_cols:
                print(f"✗ Missing columns in interim_shills: {missing_cols}")
                return False
            
            print(f"✓ All required tables exist: {', '.join(required_tables)}")
            print(f"✓ interim_shills table has required columns")
            return True
    except Exception as e:
        print(f"✗ Database schema test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_registration_ingest(s: any):
    """Test 6: Test registration ingestion (requires API key)."""
    print("\n=== Test 6: Registration Ingestion (API) ===")
    if not s.scrapingdog_api_key:
        print("⚠ Skipped: No API key set")
        return None
    
    try:
        from shillbot.cli import cmd_ingest_registrations
        print("  Running: python -m shillbot ingest-registrations")
        cmd_ingest_registrations()
        
        # Check results
        db = DB(s.db_path)
        with connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM registrations").fetchone()[0]
            print(f"  ✓ Registrations in DB: {count}")
            if count > 0:
                rows = conn.execute("SELECT handle, wallet FROM registrations ORDER BY registered_at_utc DESC LIMIT 5").fetchall()
                print("  Recent registrations:")
                for r in rows:
                    print(f"    {r['handle']} -> {r['wallet'][:16]}...")
        
        return True
    except Exception as e:
        print(f"✗ Registration ingest failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_interim_pull(s: any):
    """Test 7: Test interim shill pull (requires API key)."""
    print("\n=== Test 7: Interim Shill Pull (API) ===")
    if not s.scrapingdog_api_key:
        print("⚠ Skipped: No API key set")
        return None
    
    try:
        # Use last 24 hours - handle timezone gracefully
        from datetime import timezone as tz_utc
        try:
            until_dt = datetime.now(ZoneInfo(s.timezone))
            since_dt = until_dt - timedelta(hours=24)
            since_utc = since_dt.astimezone(tz_utc.utc).isoformat()
            until_utc = until_dt.astimezone(tz_utc.utc).isoformat()
        except Exception:
            # Fallback to UTC if timezone fails
            until_dt = datetime.now(tz_utc.utc)
            since_dt = until_dt - timedelta(hours=24)
            since_utc = since_dt.isoformat()
            until_utc = until_dt.isoformat()
        
        
        print(f"  Pulling tweets from {since_utc[:19]} to {until_utc[:19]}")
        
        from shillbot.cli import cmd_ingest
        cmd_ingest(interim=True, since=since_utc, until=until_utc)
        
        # Check results
        db = DB(s.db_path)
        with connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM interim_shills").fetchone()[0]
            print(f"  ✓ Interim shills in DB: {count}")
            if count > 0:
                rows = conn.execute("SELECT handle, tweet_id, created_at_utc FROM interim_shills ORDER BY created_at_utc DESC LIMIT 5").fetchall()
                print("  Recent tweets:")
                for r in rows:
                    print(f"    {r['handle']}: {r['tweet_id']} at {r['created_at_utc'][:19]}")
        
        return True
    except Exception as e:
        print(f"✗ Interim pull failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_csv_export(s: any):
    """Test 8: Test CSV export."""
    print("\n=== Test 8: CSV Export ===")
    try:
        db = DB(s.db_path)
        with connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) as cnt FROM interim_shills").fetchone()[0]
            if count == 0:
                print("⚠ Skipped: No interim shills to export")
                return None
        
        from shillbot.cli import cmd_export_interim
        cmd_export_interim(csv_only=True)
        
        import os
        import glob
        csv_files = glob.glob(os.path.join(s.public_dir, "exports", "interim_*.csv"))
        if csv_files:
            latest = max(csv_files, key=os.path.getctime)
            print(f"  ✓ CSV exported: {latest}")
            # Show first few lines
            with open(latest, 'r') as f:
                lines = f.readlines()[:5]
                print("  First few lines:")
                for line in lines:
                    print(f"    {line.strip()}")
            return True
        else:
            print("  ✗ No CSV file created")
            return False
    except Exception as e:
        print(f"✗ CSV export failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("X/Twitter Ingest Manual Test Suite")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Config
    s = test_config()
    results['config'] = s is not None
    if not s:
        print("\n✗ Cannot continue without valid config")
        sys.exit(1)
    
    # Test 2: Validation
    results['validation'] = test_validation()
    
    # Test 3: Registration parsing
    results['registration_parsing'] = test_registration_parsing(s)
    
    # Test 4: Rate limiting
    results['rate_limiting'] = test_rate_limiting()
    
    # Test 5: Database schema
    results['database'] = test_database_schema()
    
    # Test 6: Registration ingest (requires API)
    results['registration_ingest'] = test_registration_ingest(s)
    
    # Test 7: Interim pull (requires API)
    results['interim_pull'] = test_interim_pull(s)
    
    # Test 8: CSV export
    results['csv_export'] = test_csv_export(s)
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, result in results.items():
        if result is None:
            status = "⚠ SKIPPED"
        elif result:
            status = "✓ PASSED"
        else:
            status = "✗ FAILED"
        print(f"  {test_name:25} {status}")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\n✓ All tests passed!")


if __name__ == "__main__":
    main()
