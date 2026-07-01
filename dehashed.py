#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = ["requests>=2.28"]
# ///
"""
dehashed.py — a command-line client for the DeHashed v2 API.

Search DeHashed across any field (email, username, domain, IP, name, phone,
password, hash, address, VIN) or with a raw query, page through results
automatically, and export as a table, JSON/JSONL, CSV, or classic
identifier:password / identifier:hash combolists.

API key resolution order:
    1. --key / -k
    2. $DEHASHED_API_KEY
    3. ~/.config/dehashed/config.json   (write it once with --save-key)

Docs: https://dehashed.com/  •  v2 API: POST https://api.dehashed.com/v2/search
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("[-] Missing dependency 'requests'. Install it (pip install requests) "
             "or run via uv: uv run dehashed.py ...")

__version__ = "2.0.0"

API_BASE = "https://api.dehashed.com/v2"
SEARCH_URL = f"{API_BASE}/search"
SEARCH_PASSWORD_URL = f"{API_BASE}/search-password"

MAX_SIZE = 10_000          # max results the API returns per page
RESULT_CAP = 10_000        # the API refuses to paginate beyond 10k results
CONFIG_PATH = Path.home() / ".config" / "dehashed" / "config.json"

# CLI field flag -> DeHashed query operator (also the result field names).
SEARCH_FIELDS = [
    "email", "username", "domain", "ip_address", "password",
    "hashed_password", "name", "phone", "address", "vin",
]

# Preferred left-to-right column order for the table / CSV output.
PREFERRED_COLUMNS = [
    "email", "username", "password", "hashed_password", "hash_type",
    "name", "phone", "ip_address", "address", "company", "domain", "vin",
    "database", "database_name",
]

_COLOR = False


# --------------------------------------------------------------------------- #
# Small output helpers (status -> stderr, data -> stdout, so piping stays clean)
# --------------------------------------------------------------------------- #
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def eprint(*args) -> None:
    print(*args, file=sys.stderr)


def info(msg: str) -> None:
    eprint(_c("94", "[*] ") + msg)


def ok(msg: str) -> None:
    eprint(_c("92", "[+] ") + msg)


def warn(msg: str) -> None:
    eprint(_c("93", "[!] ") + msg)


def die(msg: str, code: int = 1) -> "None":
    eprint(_c("91", "[-] ") + msg)
    sys.exit(code)


# --------------------------------------------------------------------------- #
# Value coercion — v2 returns every field as a list of strings.
# --------------------------------------------------------------------------- #
_EMPTY = (None, "", "null", [])


def first(value) -> str:
    """First meaningful value, whether the field is a list or a scalar."""
    if isinstance(value, list):
        for v in value:
            if v not in _EMPTY:
                return str(v)
        return ""
    return "" if value in (None, "null") else str(value)


def flat(value, sep: str = ", ") -> str:
    """Join a (possibly list-valued) field into a single display string."""
    if isinstance(value, list):
        return sep.join(str(v) for v in value if v not in _EMPTY)
    return "" if value in (None, "null") else str(value)


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #
class DehashedError(Exception):
    pass


class Dehashed:
    def __init__(self, api_key: str, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Dehashed-Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _post(self, url: str, payload: dict) -> dict:
        for attempt in range(5):
            try:
                resp = self.session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                raise DehashedError(f"network error: {exc}")

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                warn(f"rate limited (429), retrying in {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                detail = ""
                try:
                    body = resp.json()
                    detail = body.get("error") or body.get("message") or ""
                except ValueError:
                    detail = resp.text.strip()
                if resp.status_code in (401, 403) and not detail:
                    detail = "check your API key"
                raise DehashedError(f"HTTP {resp.status_code}: {detail}"[:400])
            try:
                return resp.json()
            except ValueError:
                raise DehashedError(f"non-JSON response: {resp.text.strip()[:300]}")

        raise DehashedError("still rate limited (429) after several retries")

    def search(self, query: str, *, size: int = MAX_SIZE, wildcard: bool = False,
               regex: bool = False, de_dupe: bool = False,
               max_results: int = RESULT_CAP) -> dict:
        """Run a search, transparently paging up to the API's 10k cap."""
        size = max(1, min(size, MAX_SIZE))
        entries: list[dict] = []
        total = 0
        balance = None
        page = 1

        while True:
            data = self._post(SEARCH_URL, {
                "query": query, "page": page, "size": size,
                "wildcard": wildcard, "regex": regex, "de_dupe": de_dupe,
            })
            total = data.get("total") or 0
            balance = data.get("balance", balance)
            batch = data.get("entries") or []
            entries.extend(batch)

            reachable = min(total, max_results, RESULT_CAP)
            if total > size:
                info(f"fetched {len(entries)}/{reachable}...")
            if not batch or len(entries) >= reachable or page * size >= RESULT_CAP:
                break
            page += 1
            time.sleep(0.15)  # stay friendly to the rate limiter

        if total > RESULT_CAP:
            warn(f"{total} total results but the API caps retrieval at {RESULT_CAP}; "
                 "narrow your query to see the rest.")
        return {"entries": entries[:max_results], "total": total, "balance": balance}

    def search_password(self, password_hash: str) -> dict:
        """Free lookup of a password hash (no credits consumed)."""
        return self._post(SEARCH_PASSWORD_URL, {"hash": password_hash})


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def resolve_api_key(args) -> "str | None":
    return args.key or os.environ.get("DEHASHED_API_KEY") or load_config().get("api_key")


def save_api_key(key: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"api_key": key}, indent=2) + "\n")
    os.chmod(CONFIG_PATH, 0o600)


# --------------------------------------------------------------------------- #
# Query building
# --------------------------------------------------------------------------- #
def build_query(args) -> "str | None":
    if args.query:
        return args.query

    terms = []
    for field in SEARCH_FIELDS:
        value = getattr(args, field, None)
        if not value:
            continue
        if field == "domain":
            terms.append(f"domain:{value}")            # domains reject quotes
        elif args.wildcard or args.regex:
            terms.append(f"{field}:{value}")            # no quotes with ?/*/regex
        else:
            terms.append(f'{field}:"{value}"')          # exact match
    if not terms:
        return None
    return (" OR " if args.or_ else " AND ").join(terms)


# --------------------------------------------------------------------------- #
# Output rendering
# --------------------------------------------------------------------------- #
def choose_columns(entries: list[dict], override: "str | None") -> list[str]:
    if override:
        return [c.strip() for c in override.split(",") if c.strip()]
    present = {k for e in entries for k, v in e.items()
               if v not in _EMPTY and k != "id"}
    cols = [c for c in PREFERRED_COLUMNS if c in present]
    cols += [k for k in sorted(present) if k not in cols]
    return cols


def render_table(entries: list[dict], columns: list[str], cap: int = 44) -> str:
    rows = [[flat(e.get(c)) for c in columns] for e in entries]
    widths = [len(c) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    widths = [min(w, cap) for w in widths]

    def fmt(cells):
        out = []
        for i, cell in enumerate(cells):
            if len(cell) > widths[i]:
                cell = cell[: widths[i] - 1] + "…"
            out.append(cell.ljust(widths[i]))
        return "  ".join(out).rstrip()

    lines = [_c("1", fmt(columns)), fmt(["-" * w for w in widths])]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


def combo_lines(entries: list[dict]) -> "tuple[list[str], list[str]]":
    creds, hashes = [], []
    for e in entries:
        ident = first(e.get("email")) or first(e.get("username")) or first(e.get("domain"))
        pw = first(e.get("password"))
        h = first(e.get("hashed_password"))
        if pw:
            creds.append(f"{ident}:{pw}")
        elif h:
            hashes.append(f"{ident}:{h}")
    return creds, hashes


def write_csv(entries: list[dict], fh) -> None:
    keys = choose_columns(entries, None)
    # append any remaining populated keys so nothing is silently dropped
    extra = sorted({k for e in entries for k, v in e.items()
                    if v not in _EMPTY and k not in keys and k != "id"})
    fieldnames = keys + extra
    writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        writer.writerow({k: flat(e.get(k)) for k in fieldnames})


def infer_format(path: "str | None", explicit: "str | None") -> str:
    if explicit:
        return explicit
    if path:
        ext = Path(path).suffix.lower()
        return {".csv": "csv", ".json": "json", ".jsonl": "jsonl",
                ".txt": "combo"}.get(ext, "csv")
    return "table"


def emit(entries: list[dict], fmt: str, path: "str | None", columns_override: "str | None") -> None:
    fh = open(path, "w", newline="", encoding="utf-8") if path else sys.stdout
    try:
        if fmt == "csv":
            write_csv(entries, fh)
        elif fmt == "json":
            json.dump(entries, fh, indent=2)
            fh.write("\n")
        elif fmt == "jsonl":
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        elif fmt == "combo":
            creds, hashes = combo_lines(entries)
            fh.write("\n".join(creds))
            if creds and hashes:
                fh.write("\n")
            fh.write("\n".join(hashes))
            if creds or hashes:
                fh.write("\n")
        else:  # table
            fh.write(render_table(entries, choose_columns(entries, columns_override)) + "\n")
    finally:
        if fh is not sys.stdout:
            fh.close()
            ok(f"wrote {len(entries)} entries to {path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="dehashed.py",
        description="Query the DeHashed v2 API from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  dehashed.py --save-key                       # store your API key once\n"
            "  dehashed.py -d example.com -o creds.txt      # dump a domain to a combolist\n"
            "  dehashed.py -e admin@example.com             # look up an email\n"
            "  dehashed.py -u jsmith --format json          # JSON to stdout\n"
            "  dehashed.py -d example.com --only-passwords  # just cracked creds\n"
            "  dehashed.py -q 'username:adm?n' --wildcard   # raw query + wildcard\n"
            "  dehashed.py --password-lookup 5f4dcc3b5aa765d61d8327deb882cf99  # free hash lookup\n"
        ),
    )

    s = p.add_argument_group("search fields (combine with AND, or use --or)")
    s.add_argument("-e", "--email", help="Search by email address")
    s.add_argument("-u", "--username", help="Search by username")
    s.add_argument("-d", "--domain", help="Search by domain")
    s.add_argument("-i", "--ip", dest="ip_address", help="Search by IP address")
    s.add_argument("-n", "--name", help="Search by name")
    s.add_argument("-p", "--phone", help="Search by phone number")
    s.add_argument("-a", "--address", help="Search by address")
    s.add_argument("--password", help="Search by cleartext password")
    s.add_argument("-H", "--hash", dest="hashed_password", help="Search by password hash")
    s.add_argument("--vin", help="Search by VIN")
    s.add_argument("-q", "--query", help="Raw DeHashed query (overrides field flags)")

    o = p.add_argument_group("search options")
    o.add_argument("--or", dest="or_", action="store_true",
                   help="Combine field flags with OR instead of AND")
    o.add_argument("--wildcard", action="store_true", help="Enable ? / * wildcard matching")
    o.add_argument("--regex", action="store_true", help="Treat the query as regex")
    o.add_argument("--dedupe", dest="de_dupe", action="store_true",
                   help="Ask the API to de-duplicate entries")
    o.add_argument("--size", type=int, default=MAX_SIZE,
                   help=f"Results per page, 1-{MAX_SIZE} (default: {MAX_SIZE})")
    o.add_argument("--max", dest="max_results", type=int, default=RESULT_CAP,
                   help=f"Stop after this many results (default: {RESULT_CAP})")
    o.add_argument("--only-passwords", action="store_true",
                   help="Keep only entries that have a cleartext password")

    out = p.add_argument_group("output")
    out.add_argument("-o", "--output", help="Write to FILE (format inferred from extension)")
    out.add_argument("-f", "--format", choices=["table", "json", "jsonl", "csv", "combo"],
                     help="Output format (default: table, or inferred from -o)")
    out.add_argument("--fields", help="Comma-separated columns for table/csv output")
    out.add_argument("--no-color", action="store_true", help="Disable ANSI color")

    other = p.add_argument_group("misc")
    other.add_argument("--password-lookup", metavar="HASH",
                       help="Free lookup of a password hash via /v2/search-password")
    other.add_argument("-k", "--key", help="DeHashed API key")
    other.add_argument("--save-key", action="store_true",
                       help=f"Save the API key to {CONFIG_PATH} and exit")
    other.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds (default: 30)")
    other.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    return p.parse_args(argv)


def main(argv=None) -> int:
    global _COLOR
    args = parse_args(argv)
    _COLOR = sys.stdout.isatty() and not args.no_color and os.environ.get("NO_COLOR") is None

    if not 1 <= args.size <= MAX_SIZE:
        die(f"--size must be between 1 and {MAX_SIZE}", 2)

    if args.save_key:
        key = args.key or getpass.getpass("DeHashed API key: ").strip()
        if not key:
            die("no key provided", 2)
        save_api_key(key)
        ok(f"API key saved to {CONFIG_PATH}")
        return 0

    api_key = resolve_api_key(args)
    if not api_key:
        die("no API key found. Use --key, set DEHASHED_API_KEY, or run --save-key.", 2)

    client = Dehashed(api_key, timeout=args.timeout)

    try:
        if args.password_lookup:
            result = client.search_password(args.password_lookup)
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0

        query = build_query(args)
        if not query:
            die("no search criteria. Provide a field flag (e.g. -d example.com) or -q QUERY.", 2)

        info(f"query: {query}")
        result = client.search(
            query, size=args.size, wildcard=args.wildcard, regex=args.regex,
            de_dupe=args.de_dupe, max_results=args.max_results,
        )
    except DehashedError as exc:
        die(str(exc))

    entries = result["entries"]
    if args.only_passwords:
        entries = [e for e in entries if first(e.get("password"))]

    balance = result["balance"]
    tail = f" — {balance} credits remaining" if balance is not None else ""
    info(f"{len(entries)} entries (of {result['total']} total){tail}")

    if not entries:
        warn("no results")
        return 0

    emit(entries, infer_format(args.output, args.format), args.output, args.fields)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        die("interrupted", 130)
