#!/usr/bin/env python3
"""
Quick test script for X API implementation.
Tests basic functionality without requiring Bearer token (for syntax/import checks).
"""

from __future__ import annotations

from shillbot.config import load_settings
from shillbot.x_api import XAPIClient
from shillbot.x_ingest import XIngestor


def test_config():
    """Test configuration loading."""
    print("\n=== Test 1: Configuration ===")
    try:
        s = load_settings()
        print("OK: Config loaded successfully")
        print(f"  X API Bearer Token set: {bool(s.x_api_bearer_token)}")
        print(f"  Coin handle: {s.coin_handle}")
        print(f"  Coin ticker: {s.coin_ticker}")
        print(f"  Register hashtag: {s.register_hashtag}")
        return s
    except Exception as e:
        print(f"FAILED: Config failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_x_api_client():
    """Test X API client instantiation."""
    print("\n=== Test 2: X API Client ===")
    try:
        # Test with dummy token (just to test instantiation)
        client = XAPIClient(bearer_token="test_token", timeout_s=30)
        print("OK: XAPIClient created successfully")
        print(f"  BASE_URL: {client.BASE_URL}")
        return True
    except Exception as e:
        print(f"FAILED: XAPIClient creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_x_ingestor():
    """Test X Ingestor instantiation."""
    print("\n=== Test 3: X Ingestor ===")
    try:
        s = load_settings()
        client = XAPIClient(bearer_token="test_token", timeout_s=30)
        ingestor = XIngestor(
            client=client,
            handle=s.handle,
            coin_handle=s.coin_handle,
            coin_ticker=s.coin_ticker,
            token_mint=s.token_mint if s.token_mint else None,
            register_hashtag=s.register_hashtag,
        )
        print("OK: XIngestor created successfully")
        return True
    except Exception as e:
        print(f"FAILED: XIngestor creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_registration_parsing():
    """Test registration hashtag parsing."""
    print("\n=== Test 4: Registration Parsing ===")
    try:
        s = load_settings()
        client = XAPIClient(bearer_token="test_token", timeout_s=30)
        ingestor = XIngestor(
            client=client,
            handle=s.handle,
            coin_handle=s.coin_handle,
            coin_ticker=s.coin_ticker,
            token_mint=s.token_mint if s.token_mint else None,
            register_hashtag=s.register_hashtag,
        )
        
        test_cases = [
            ("#Shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", True),
            ("#shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", True),
            ("Check out #Shillbot-register C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", True),
            ("#Shillbot-register invalid", False),
        ]
        
        passed = 0
        for text, should_find in test_cases:
            wallet = ingestor.parse_registration_hashtag(text)
            found = wallet is not None
            if found == should_find:
                passed += 1
                status = "OK" if found else "OK (correctly rejected)"
                print(f"  {status} '{text[:50]}...' -> {wallet}")
            else:
                print(f"  FAILED '{text[:50]}...' -> Expected {should_find}, got {found}")
        
        print(f"OK: Registration parsing: {passed}/{len(test_cases)} tests passed")
        return passed == len(test_cases)
    except Exception as e:
        print(f"FAILED: Registration parsing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_with_real_api(s):
    """Test with real X API (if Bearer token is set)."""
    print("\n=== Test 5: X API Integration (Requires Bearer Token) ===")
    if not s.x_api_bearer_token:
        print("⚠ Skipped: SHILLBOT_X_API_BEARER_TOKEN not set")
        print("  To test with real API:")
        print("  1. Set SHILLBOT_X_API_BEARER_TOKEN in .env")
        print("  2. Run: python -m shillbot ingest-registrations")
        print("  3. Run: python -m shillbot ingest --interim --since 2026-01-10T00:00:00Z --until 2026-01-10T23:59:59Z")
        return None
    
    try:
        from shillbot.cli import cmd_ingest_registrations
        
        print("  Testing registration ingestion...")
        cmd_ingest_registrations()
        
        print("OK: Registration ingestion completed")
        print("  (Check output above for results)")
        return True
    except Exception as e:
        print(f"FAILED: X API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("X API Implementation Test Suite")
    print("=" * 60)
    
    results = {}
    
    results['config'] = test_config() is not None
    results['x_api_client'] = test_x_api_client()
    results['x_ingestor'] = test_x_ingestor()
    results['registration_parsing'] = test_registration_parsing()
    
    s = load_settings()
    results['real_api'] = test_with_real_api(s)
    
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
        print(f"  {test_name:25} {status}")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed > 0:
        import sys
        sys.exit(1)
    else:
        print("\nOK: All tests passed!")


if __name__ == "__main__":
    main()
