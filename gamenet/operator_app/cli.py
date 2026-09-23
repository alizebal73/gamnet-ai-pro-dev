"""Operator shell: a thin stdlib CLI over the HTTP API (P3-5).

Everyday counter flows without touching the database directly:
login, quick-customer, quick-sale, session end, queue listing and shift
open/close. The HTTP layer is injectable so the commands are unit
testable without a live server.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable

ApiCall = Callable[..., dict]


class CliError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def http_call(base_url: str, method: str, path: str, *,
              token: str | None = None,
              body: dict | None = None) -> dict:
    url = base_url.rstrip("/") + path
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
        except ValueError:
            detail = exc.reason
        raise CliError(f"HTTP {exc.code}: {detail}", status=exc.code)
    except urllib.error.URLError as exc:
        raise CliError(f"Cannot reach server: {exc.reason}")
    if not raw.strip():
        return {"ok": True}
    try:
        return json.loads(raw)
    except ValueError:
        raise CliError(f"Non-JSON response: {raw[:200]}")


def _call(base_url: str, token: str | None, method: str, path: str,
          body: dict | None = None) -> dict:
    return http_call(base_url, method, path, token=token, body=body)


def cmd_login(args: argparse.Namespace, call: ApiCall) -> dict:
    return call("POST", "/api/v1/auth/login",
                {"username": args.username, "password": args.password})


def cmd_quick_customer(args: argparse.Namespace, call: ApiCall) -> dict:
    body = {"name": args.name, "pin": args.pin}
    if args.mobile:
        body["mobile"] = args.mobile
    if args.gaming_name:
        body["gaming_name"] = args.gaming_name
    if args.recharge:
        body["recharge_amount"] = args.recharge
    return call("POST", "/api/v1/quick/customer", body)


def cmd_quick_sale(args: argparse.Namespace, call: ApiCall) -> dict:
    items = [json.loads(raw) for raw in args.item]
    payments = []
    for raw in args.pay:
        method, _, amount = raw.partition(":")
        payments.append({"method": method.strip(),
                         "amount": int(amount.strip())})
    body: dict = {"customer_id": args.customer, "items": items,
                  "payments": payments}
    if args.discount_pct:
        body["discount_pct"] = args.discount_pct
    if args.discount_reason:
        body["discount_reason"] = args.discount_reason
    return call("POST", "/api/v1/quick/sale", body)


def cmd_session_end(args: argparse.Namespace, call: ApiCall) -> dict:
    body = {"reason": args.reason} if args.reason else {}
    return call("POST", f"/api/v1/sessions/{args.session_id}/end", body)


def cmd_queue(args: argparse.Namespace, call: ApiCall) -> dict:
    del args
    return call("GET", "/api/v1/queue")


def cmd_shift_open(args: argparse.Namespace, call: ApiCall) -> dict:
    return call("POST", "/api/v1/shifts/open",
                {"opening_float": args.opening_float})


def cmd_shift_close(args: argparse.Namespace, call: ApiCall) -> dict:
    body = {"counted_cash": args.counted_cash}
    if args.note:
        body["note"] = args.note
    return call("POST", "/api/v1/shifts/current/close", body)


_COMMANDS = {
    "login": cmd_login,
    "quick-customer": cmd_quick_customer,
    "quick-sale": cmd_quick_sale,
    "session-end": cmd_session_end,
    "queue": cmd_queue,
    "shift-open": cmd_shift_open,
    "shift-close": cmd_shift_close,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamnet-operator",
        description="Operator shell for the GameNet server.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8000",
                        help="Server base URL")
    parser.add_argument("--token", default=None,
                        help="Operator token (from login)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="Log in as an operator")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)

    p = sub.add_parser("quick-customer",
                       help="Register a customer, optionally with credit")
    p.add_argument("--name", required=True)
    p.add_argument("--pin", required=True)
    p.add_argument("--mobile", default=None)
    p.add_argument("--gaming-name", default=None)
    p.add_argument("--recharge", type=int, default=None)

    p = sub.add_parser("quick-sale",
                       help="Draft + pay + confirm in one call")
    p.add_argument("--customer", required=True)
    p.add_argument("--item", action="append", required=True,
                   help='Sale item as JSON, e.g. \'{"kind":"TIME",'
                        '"duration_sec":3600}\' (repeatable)')
    p.add_argument("--pay", action="append", required=True,
                   help='"METHOD:AMOUNT", e.g. CASH:500000 (repeatable)')
    p.add_argument("--discount-pct", type=int, default=0)
    p.add_argument("--discount-reason", default=None)

    p = sub.add_parser("session-end", help="End a session")
    p.add_argument("session_id")
    p.add_argument("--reason", default=None)

    sub.add_parser("queue", help="List waiting customers")

    p = sub.add_parser("shift-open", help="Open a shift")
    p.add_argument("--opening-float", type=int, required=True)

    p = sub.add_parser("shift-close", help="Close the current shift")
    p.add_argument("--counted-cash", type=int, required=True)
    p.add_argument("--note", default=None)
    return parser


def main(argv: list[str] | None = None,
         call: ApiCall | None = None) -> int:
    args = build_parser().parse_args(argv)
    if call is None:
        base_url, token = args.server, args.token
        call = lambda method, path, body=None: _call(  # noqa: E731
            base_url, token, method, path, body)
    try:
        result = _COMMANDS[args.command](args, call)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: bad argument: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
