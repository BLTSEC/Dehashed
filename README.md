# dehashed.py

A fast, single-file command-line client for the **[DeHashed](https://dehashed.com) v2 API**.

Search any field, page through results automatically, and export as a table,
JSON/JSONL, CSV, or classic `identifier:password` / `identifier:hash`
combolists — with your API key kept out of the source.

```
$ dehashed.py -d example.com --only-passwords
[*] query: domain:example.com
[*] 128 entries (of 128 total) — 4871 credits remaining
email                     password
------------------------  -------------
brady@example.com         Summer1999!
copper@example.com         hunter2
...
```

## Features

- **Search every field** — email, username, domain, IP, name, phone, password,
  hash, address, VIN — or pass a raw `-q` query.
- **Combine criteria** with `AND` (default) or `--or`, plus `--wildcard` (`?` / `*`)
  and `--regex`.
- **Automatic pagination** up to the API's 10,000-result cap, with `--size` /
  `--max` controls and 429 rate-limit backoff.
- **Multiple outputs** — `table` (default), `json`, `jsonl`, `csv`, `combo`;
  auto-inferred from the `-o` file extension.
- **Safe key handling** — `--key`, `$DEHASHED_API_KEY`, or a `0600` config file
  (`--save-key`). Nothing hardcoded.
- **Pipe-friendly** — data goes to stdout, status/progress to stderr.
- **Free password-hash lookup** via `--password-lookup` (no credits used).
- One dependency (`requests`); works anywhere Python 3.8+ runs.

## Install

### With uv (recommended)

The script declares its dependency inline ([PEP 723](https://peps.python.org/pep-0723/)),
so [uv](https://docs.astral.sh/uv/) can run it with **zero setup** — it builds and
caches a throwaway environment automatically:

```bash
git clone https://github.com/BLTSEC/Dehashed && cd Dehashed
uv run dehashed.py --version
uv run dehashed.py -d example.com -o creds.txt
```

Prefer a persistent project venv? uv handles that too:

```bash
uv venv                              # create .venv
uv pip install -r requirements.txt   # just 'requests'
source .venv/bin/activate
./dehashed.py -d example.com
```

### With pipx (installs a `dehashed` command)

For a permanent, isolated `dehashed` on your `PATH`:

```bash
git clone https://github.com/BLTSEC/Dehashed && cd Dehashed
pipx install .
dehashed --version
dehashed -d example.com -o loot/example.txt
```

Update after pulling changes with `pipx install --force .`.

### With pip

```bash
git clone https://github.com/BLTSEC/Dehashed && cd Dehashed
pip install -r requirements.txt      # just 'requests'
chmod +x dehashed.py
./dehashed.py --version
```

## Setup

Store your DeHashed API key once (written to `~/.config/dehashed/config.json`, mode `600`):

```bash
./dehashed.py --save-key
```

Or provide it per-run with `--key`, or export `DEHASHED_API_KEY`.

## Usage

```
usage: dehashed.py [-e EMAIL] [-u USERNAME] [-d DOMAIN] [-i IP] [-n NAME]
                   [-p PHONE] [-a ADDRESS] [--password PASSWORD] [-H HASH]
                   [--vin VIN] [-q QUERY] [--or] [--wildcard] [--regex]
                   [--dedupe] [--size N] [--max N] [--only-passwords]
                   [-o OUTPUT] [-f {table,json,jsonl,csv,combo}] [--fields COLS]
                   [--no-color] [--password-lookup HASH] [-k KEY] [--save-key]
                   [--timeout SECONDS] [--version]
```

### Examples

```bash
# Dump everything for a domain to a combolist (email:password / email:hash)
./dehashed.py -d example.com -o example.txt

# Look up an email, print JSON
./dehashed.py -e admin@example.com --format json

# Username + domain (AND), only records with a cleartext password, to CSV
./dehashed.py -u jsmith -d example.com --only-passwords -o hits.csv

# Wildcard username search (use ? for single chars; * is flaky server-side)
./dehashed.py -q 'username:adm?n' --wildcard

# Free lookup of a password hash — no API credits consumed
./dehashed.py --password-lookup 5f4dcc3b5aa765d61d8327deb882cf99
```

### Output formats

| Format  | Description                                              |
|---------|----------------------------------------------------------|
| `table` | Aligned columns of the populated fields (default)        |
| `json`  | Pretty JSON array of raw entries                         |
| `jsonl` | One JSON object per line (great for piping/`jq`)         |
| `csv`   | Spreadsheet-friendly; all populated fields as columns    |
| `combo` | `identifier:password` then `identifier:hash` lines       |

If you pass `-o file.csv` / `.json` / `.jsonl` / `.txt` the format is inferred
from the extension; override with `-f`.

## Notes

- The DeHashed API returns at most **10,000 results** per query — narrow your
  query (e.g. add a second field) to reach data beyond that.
- Wildcard `*` searches are known to be unreliable server-side; prefer `?`.
- This is an OSINT / authorized-security-testing tool. Use it only against data
  and targets you are permitted to investigate.

## License

MIT — see [`LICENSE`](LICENSE).
