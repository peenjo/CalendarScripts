#!/usr/bin/env python3
"""
qif_to_qfx.py — Convert a QIF file to OFX/QFX for import into Quicken macOS.

Repeatable by design: FITIDs are deterministic (derived from transaction
content), so re-running on the same QIF produces identical output and Quicken
recognises the transactions as already imported.

Quicken Mac compatibility notes:
  * Writes CRLF line endings and an OFX 1.02 SGML header, as the OFX spec and
    Quicken's Web Connect parser expect.
  * Includes an INTU.BID header line. Quicken validates this bank identifier
    before accepting a Web Connect file. Default is 71901 (a currently active
    value that bypasses the "inactive FI" error).

Requires: pip install python-dateutil

Usage:
    python3 qif_to_qfx.py input.qif
        # Output will be input.qfx in the same directory

    python3 qif_to_qfx.py input.qif --intubid 3000 --acctid MYACC123
        # Override BID or account ID if needed

Options:
  --intubid INTUBID    Bank identifier (default: 71901). If you get "inactive FI",
                       try 3000 (Wells Fargo) or another active BID.
  --acctid ACCTID      Account ID placeholder (default: derived from input filename).
  --accttype TYPE      CHECKING | SAVINGS | CCARD (auto-detected from !Type: if omitted).
  --currency CODE      ISO currency code (default: EUR).
  --flip-signs         Negate every amount (use if your QIF sign convention is inverted).
  --debug              Print skipped records and parsing info.
"""

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime

try:
    from dateutil import parser as date_parser
except ImportError:
    sys.exit("Missing dependency. Run: pip install python-dateutil")

# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

LINE_RE = re.compile(r"^([A-Za-z!])(.*)$")


def _clean(value):
    """Strip surrounding whitespace and stray leading/trailing separators."""
    return value.strip().strip("|").strip()


def parse_qif(path):
    """
    Parse a QIF file into (header_type, [transaction dicts]).

    Returns the declared !Type: header (e.g. 'Bank') plus a list of dicts with
    keys: date, amount, payee, memo, number, cleared, category, address.

    A 'D' line while the current record already has a date is treated as an
    implicit record boundary (handles QIFs with missing '^' terminators).
    Other field lines never start a new record — a valid QIF record can contain
    at most one of each, and repeats simply overwrite.
    """
    transactions = []
    current = {}
    header_type = None

    def flush():
        nonlocal current
        if current:
            transactions.append(current)
        current = {}

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\r\n")
            if not line.strip():
                continue

            match = LINE_RE.match(line)
            if not match:
                continue

            code, value = match.group(1), _clean(match.group(2))

            # Header lines: !Type:Bank, !Account, !Option:AutoSwitch ...
            if code == "!":
                if line.startswith("!Type:"):
                    header_type = value
                continue

            # Record terminator
            if code == "^":
                flush()
                continue

            # Implicit record boundary: a new date while one is already present.
            # Only 'D' triggers this — the date is always the first field of a
            # QIF record, whereas N/T/P/M can legitimately follow it.
            if code == "D" and "date" in current:
                flush()

            if code == "D":
                current["date"] = value
            elif code == "T":
                current["amount"] = value
            elif code == "P":
                current["payee"] = value
            elif code == "M":
                current["memo"] = value
            elif code == "N":
                current["number"] = value
            elif code == "C":
                current["cleared"] = value
            elif code == "L":
                current["category"] = value
            elif code == "A":
                current.setdefault("address", []).append(value)
            # Split / transfer / other codes intentionally ignored for now.

    flush()
    return header_type, transactions


# --------------------------------------------------------------------------
# Normalisation helpers
# --------------------------------------------------------------------------


def parse_amount(raw, flip=False):
    """Return a float from a QIF amount string, or None if unparseable."""
    if raw is None:
        return None
    cleaned = raw.replace(",", "").replace(" ", "")
    cleaned = re.sub(r"[^\d.\-+]", "", cleaned)
    if cleaned in ("", "-", "+", ".", "-."):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if flip else value


def ofx_datetime(raw):
    """Convert a QIF date to OFX YYYYMMDDHHMMSS. Returns None on failure."""
    if not raw:
        return None
    try:
        dt = date_parser.parse(raw, dayfirst=False)
    except (ValueError, OverflowError, TypeError):
        return None
    return dt.strftime("%Y%m%d%H%M%S")


def xml_escape(text):
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def make_fitid(tx, index, amount, dt_string):
    """
    Deterministic FITID.

    Built from date + amount + payee + memo + number. Stable across runs for
    identical input, which is what stops Quicken duplicating transactions.

    A short index is mixed in as a tiebreaker for genuinely identical
    transactions appearing more than once in the same file.
    """
    payload = "|".join(
        [
            dt_string or "",
            f"{amount:.2f}" if amount is not None else "",
            tx.get("payee", ""),
            tx.get("memo", ""),
            tx.get("number", ""),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24].upper()
    return f"QIF{digest}{index:04d}"


# --------------------------------------------------------------------------
# OFX construction
# --------------------------------------------------------------------------

ACCT_TYPE_MAP = {
    "bank": "CHECKING",
    "checking": "CHECKING",
    "savings": "SAVINGS",
    "ccard": "CCARD",
    "credit": "CCARD",
    "creditcard": "CCARD",
}


def _crlf(text):
    """Ensure every line ends with CRLF, as the OFX 1.x spec requires."""
    return "\r\n".join(text.splitlines()) + "\r\n"


def build_ofx(
        transactions, acctid, bankid, accttype, currency, intubid, flip, debug=False
):
    now = datetime.now().strftime("%Y%m%d%H%M%S")

    rows = []
    skipped = []

    for idx, tx in enumerate(transactions, start=1):
        amount = parse_amount(tx.get("amount"), flip=flip)
        dt_string = ofx_datetime(tx.get("date"))

        if amount is None or dt_string is None:
            skipped.append((idx, tx))
            continue

        trntype = "CREDIT" if amount >= 0 else "DEBIT"
        fitid = make_fitid(tx, idx, amount, dt_string)

        name = xml_escape(tx.get("payee", ""))
        memo_parts = []
        if tx.get("memo"):
            memo_parts.append(tx["memo"])
        if tx.get("number"):
            # Preserve the card reference so it survives into Quicken.
            memo_parts.append(f"[{tx['number']}]")
        memo = xml_escape(" ".join(memo_parts))

        rows.append(
            "        <STMTTRN>\n"
            f"          <TRNTYPE>{trntype}</TRNTYPE>\n"
            f"          <DTPOSTED>{dt_string}</DTPOSTED>\n"
            f"          <TRNAMT>{amount:.2f}</TRNAMT>\n"
            f"          <FITID>{fitid}</FITID>\n"
            f"          <NAME>{name}</NAME>\n"
            f"          <MEMO>{memo}</MEMO>\n"
            "        </STMTTRN>\n"
        )

    if debug and skipped:
        print(f"\n[debug] Skipped {len(skipped)} unparseable record(s):")
        for idx, tx in skipped:
            print(f"  #{idx}: {tx}")

    if not rows:
        sys.exit("No usable transactions found — nothing written.")

    dtstart = min(
        r.split("<DTPOSTED>")[1].split("<")[0] for r in rows
    )

    body = "".join(rows)

    header = (
        "OFXHEADER:100\r\n"
        "DATA:OFXSGML\r\n"
        "VERSION:102\r\n"
        "SECURITY:NONE\r\n"
        "ENCODING:USASCII\r\n"
        "CHARSET:1252\r\n"
        "COMPRESSION:NONE\r\n"
        "OLDFILEUID:NONE\r\n"
        "NEWFILEUID:NONE\r\n"
        f"INTU.BID:{intubid}\r\n"
        "\r\n"
    )

    sgml = (
        "<OFX>\r\n"
        "  <SIGNONMSGSRSV1>\r\n"
        "    <SONRS>\r\n"
        "      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>\r\n"
        f"      <DTSERVER>{now}</DTSERVER>\r\n"
        "      <LANGUAGE>ENG</LANGUAGE>\r\n"
        "      <FI>\r\n"
        f"        <ORG>CONVERTER</ORG>\r\n"
        f"        <FID>{intubid}</FID>\r\n"
        "      </FI>\r\n"
        "    </SONRS>\r\n"
        "  </SIGNONMSGSRSV1>\r\n"
        "  <BANKMSGSRSV1>\r\n"
        "    <STMTTRNRS>\r\n"
        "      <TRNUID>1</TRNUID>\r\n"
        "      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>\r\n"
        "      <STMTRS>\r\n"
        f"        <CURDEF>{currency}</CURDEF>\r\n"
        "        <BANKACCTFROM>\r\n"
        f"          <BANKID>{xml_escape(bankid)}</BANKID>\r\n"
        f"          <ACCTID>{xml_escape(acctid)}</ACCTID>\r\n"
        f"          <ACCTTYPE>{accttype}</ACCTTYPE>\r\n"
        "        </BANKACCTFROM>\r\n"
        "        <BANKTRANLIST>\r\n"
        f"          <DTSTART>{dtstart}</DTSTART>\r\n"
        f"          <DTEND>{now}</DTEND>\r\n"
        f"{_crlf(body)}"
        "        </BANKTRANLIST>\r\n"
        "        <LEDGERBAL>\r\n"
        "          <BALAMT>0.00</BALAMT>\r\n"
        f"          <DTASOF>{now}</DTASOF>\r\n"
        "        </LEDGERBAL>\r\n"
        "      </STMTRS>\r\n"
        "    </STMTTRNRS>\r\n"
        "  </BANKMSGSRSV1>\r\n"
        "</OFX>\r\n"
    )

    return header + sgml, len(rows)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Convert QIF to OFX/QFX for Quicken macOS."
    )
    ap.add_argument("input", help="source .qif file")
    ap.add_argument(
        "output",
        nargs="?",
        default=None,
        help="destination .qfx file (optional; defaults to input.qfx in same dir)",
    )
    ap.add_argument("--acctid", default=None, help="account id (placeholder)")
    ap.add_argument("--bankid", default="000000000", help="bank/routing id (placeholder)")
    ap.add_argument(
        "--intubid",
        default="71901",
        help=(
            "INTU.BID bank identifier. Default 71901 works for most modern Quicken versions. "
            "If you get 'inactive FI', try 3000 (Wells Fargo)."
        ),
    )
    ap.add_argument(
        "--accttype",
        default=None,
        help="CHECKING | SAVINGS | CCARD (auto-detected from !Type: if omitted)",
    )
    ap.add_argument("--currency", default="EUR", help="ISO currency code (default EUR)")
    ap.add_argument(
        "--flip-signs",
        action="store_true",
        help="negate every amount (use if your QIF sign convention is inverted)",
    )
    ap.add_argument("--debug", action="store_true", help="print skipped records")
    args = ap.parse_args()

    # Resolve output path
    input_path = args.input
    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(input_path)
        output_path = base + ".qfx"

    header_type, transactions = parse_qif(input_path)

    if not transactions:
        sys.exit(f"No transactions parsed from {input_path}")

    # Auto-generate acctid from filename if not provided
    if args.acctid is None:
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        # Strip non-alphanumeric, pad to 12 chars
        safe_name = re.sub(r"[^a-zA-Z0-9]", "", base_name)[:12].upper()
        args.acctid = f"{safe_name}QFX" if safe_name else "QIFIMPORT0001"

    if args.accttype:
        accttype = args.accttype.upper()
    else:
        accttype = ACCT_TYPE_MAP.get((header_type or "bank").lower(), "CHECKING")

    if args.debug:
        print(f"[debug] Input: {input_path}")
        print(f"[debug] Output: {output_path}")
        print(f"[debug] !Type: header = {header_type!r}")
        print(f"[debug] parsed {len(transactions)} transaction(s)")
        print(f"[debug] mapped account type = {accttype}")
        print(f"[debug] acctid = {args.acctid}")
        print(f"[debug] intubid = {args.intubid}")

    ofx_text, count = build_ofx(
        transactions,
        acctid=args.acctid,
        bankid=args.bankid,
        accttype=accttype,
        currency=args.currency,
        intubid=re.sub(r"\D", "", args.intubid) or "00000",
        flip=args.flip_signs,
        debug=args.debug,
    )

    with open(output_path, "wb") as fh:
        fh.write(ofx_text.encode("ascii", errors="replace"))

    print(f"Wrote {count} transaction(s) to {output_path}")
    print("Import in Quicken Mac via File > Import > Bank or Brokerage File (OFX, QFX).")
    print(f"INTU.BID used: {args.intubid}. If Quicken reports 'inactive FI', retry with --intubid 3000.")


if __name__ == "__main__":
    main()
