#!/usr/bin/env python3
"""
Foodies Cloud Project — Self-Test Verification Script
Tests health, authentication, password security, file upload limits,
type restrictions, role-based authorization (403), admin curation (200),
and private user data isolation.
"""
import sys
from app import run_self_tests

if __name__ == "__main__":
    exit_code = run_self_tests()
    sys.exit(exit_code)
