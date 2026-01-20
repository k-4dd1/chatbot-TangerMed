#!/usr/bin/env python3
"""Bulk-create users via the REST API.

This helper authenticates as the *admin* account and reads users from a CSV file,
then posts them to ``/administration/``.

The CSV file should have the following columns:
username, first_name, last_name, phone_number, email, password

Adjust ``API_BASE_URL``, ``ADMIN_USERNAME`` and ``ADMIN_PASSWORD`` as needed.
"""

from __future__ import annotations

import sys
import csv
import argparse
import httpx
from pathlib import Path
from typing import List, Dict

API_BASE_URL = "http://localhost:13537"  # Change if containerized / remote
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "bot-admin-1337"
DEFAULT_CSV_FILE = "users.csv"  # Default CSV file path

# ---------------------------------------------------------------------------
# Helpers -------------------------------------------------------------------
# ---------------------------------------------------------------------------

def read_users_from_csv(csv_path: str | Path) -> List[Dict]:
    """Read users from a CSV file and return a list of user dictionaries.
    
    Expected CSV columns: username, first_name, last_name, phone_number, email, password
    """
    users = []
    csv_path = Path(csv_path)
    
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required_fields = {"username", "first_name", "last_name", "phone_number", "email", "password"}
        
        # Validate CSV has required columns
        if not required_fields.issubset(reader.fieldnames or []):
            missing = required_fields - (set(reader.fieldnames or []))
            raise ValueError(f"CSV missing required columns: {', '.join(missing)}")
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            # Skip empty rows
            if not any(row.values()):
                continue
            
            # Create user dict with only the required fields
            user = {
                "username": row["username"].strip(),
                "first_name": row["first_name"].strip(),
                "last_name": row["last_name"].strip(),
                "phone_number": row["phone_number"].strip(),
                "email": row["email"].strip(),
                "password": row["password"].strip(),
            }
            
            # Validate required fields are not empty
            if not all(user.values()):
                print(f"Warning: Skipping row {row_num} - missing required fields")
                continue
            
            users.append(user)
    
    return users


def _obtain_access_token(client: httpx.Client) -> str:
    resp = client.post(
        f"{API_BASE_URL}/auth/token",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_users(csv_path: str | Path):
    """Create users from a CSV file."""
    try:
        users_to_create = read_users_from_csv(csv_path)
    except Exception as exc:
        print(f"Failed to read CSV file: {exc}")
        sys.exit(1)
    
    if not users_to_create:
        print("No users found in CSV file.")
        sys.exit(0)
    
    print(f"Found {len(users_to_create)} user(s) to create...")
    
    with httpx.Client() as client:
        try:
            token = _obtain_access_token(client)
        except Exception as exc:
            print(f"Failed to authenticate as admin: {exc}")
            sys.exit(1)

        headers = {"Authorization": f"Bearer {token}"}
        for user in users_to_create:
            try:
                resp = client.post(
                    f"{API_BASE_URL}/administration/",
                    json=user,
                    headers=headers,
                    timeout=15,
                )
                if resp.status_code == 201:
                    print(f"✔ Created {user['username']}")
                elif resp.status_code == 400 and resp.json().get("detail") in {"Username already exists", "Email already used", "Phone number already used"}:
                    print(f"• Skipped {user['username']} (already exists)")
                else:
                    print(f"✖ Failed to create {user['username']}: {resp.status_code} – {resp.text}")
            except Exception as exc:
                print(f"✖ Error for {user['username']}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk-create users from a CSV file")
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=DEFAULT_CSV_FILE,
        help=f"Path to CSV file with user data (default: {DEFAULT_CSV_FILE})",
    )
    args = parser.parse_args()
    
    create_users(args.csv_file)
