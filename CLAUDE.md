# CLAUDE.md

Odoo 19 modules that issue Mongolian eBarimt receipts through PosAPI 3.x (see README.md for
what each module does). Facts in this file were learned the hard way; the PR numbers say where.

## Shipping
- Work on a branch and open a PR. **Merging is deploying**: the shop PCs pull `main` and upgrade
  the modules, so a mistake on `main` fails real bills (#27 exists because #25 and #26 would
  have failed every bill from a shop PC "once it pulls main").
- Bump `version` in the changed module's `__manifest__.py`; say in the PR when deploying needs
  `-u <module>`.
- Facts about PosAPI or the shops that you learn while working go into this file, in the same PR.
- The same `ebarimt_api` and `pos_ebarimt` also live, older and diverged, in Ariyajav/smb-pos-dev.
  When you fix a bug here, say in the PR whether smb-pos-dev has the same code.

## Run the tests before you say done
`scripts/odoo-test.sh` installs every module on a fresh Odoo 19 database in Docker (odoo:19.0 and
postgres:16) and runs their tests: `scripts/odoo-test.sh pos_ebarimt` for one module,
`scripts/odoo-test.sh --install-only ebarimt_demo` for the demo module (fresh database only).
It works in a Claude Code cloud session: it starts the stopped Docker daemon itself, and the first
run pulls about 900 MB of images. CI (`.github/workflows/odoo-tests.yml`) runs it on every push.
Put the result in the commit's `Verified:` trailer, for example
`Verified: scripts/odoo-test.sh: 0 failed, 0 error(s) of 34 tests`.
Until 2026-11-05 no PR had run its tests. That day all 34 passed on `main`.

## Odoo 19
- Users' groups are `group_ids` (not `groups_id`). Demo data is off by default.
- `pos.order.get_ebarimt_receipt_data` is called from the POS as a model method with
  `(identifier, config_id)` and must keep `@api.model`. #8 inserted a new method between the
  decorator and it, so `config_id` was taken as the order and receipts printed another order's
  bill (#9; `test_receipt_data` covers it). When you add a method, keep each decorator on its own.
- Browser receipts print at 266 px (about 70 mm). 58 mm printers need the per-POS paper width,
  and the QR is sized in mm (#12).

## PosAPI 3.x
- `taxType` is one of `VAT_ABLE`, `VAT_FREE`, `VAT_ZERO`, `NOT_VAT` (PosAPI 3.2.50 refused
  `NO_VAT`, #15 → #16).
- `taxProductCode` (the product's eBarimt VAT code) is required for `VAT_FREE`, `VAT_ZERO` and
  `NOT_VAT` items and is a 3 to 10 digit number (#17, #18).
- `customerTin` is 11 to 14 digits. Cashiers type a 7-digit company registry number, which the
  server turns into the TIN through eBarimt (#13). `consumerNo` is a string, and only a real
  8-digit consumer number: `false` there made PosAPI reject the whole receipt (smb-pos-dev #2).
- POS bill types are `B2C_RECEIPT` and `B2B_RECEIPT` only (#25).
- City tax (НХАТ): PosAPI accepts only 2% (#7).
- Sending stored bills is `/rest/sendData` (HTTP 200 means sent), not `/rest/send`. `/rest/info`
  gives the last sent date (#21).
- PosAPI returns the bill date in Ulaanbaatar local time. `sent_at` is the server's time (its
  clock is synced with the tax agency). The raw PosAPI string stays in `posapi_date`, which
  returns need (#24).
- District codes come from `getBranchInfo`; a partner's district code must be the `districtCode`
  PosAPI expects. With neither a POS branch code nor a company district code, the system parameter
  `ebarimt.default_district_code` applies, else 2426 (#22, #23).
- Product classification codes (BUNA) are 7 digits, and products accept only codes loaded with
  the БҮНА код татах wizard (#14).
- Calls time out (3 s connect, 10 s read; less for the pre-sale warning check). The POS runs with
  workers=0, so a gateway that never answers would otherwise freeze the cashier's Validate button
  (smb-pos-dev F2).

## How shops reach PosAPI
- Usually through a gateway that takes an `X-API-Key` header, set on the PosAPI record.
- Shops reach that gateway over plain http, on the LAN or over Tailscale. With a key set,
  `_ebarimt_base_url` requires https except to localhost, private LAN addresses and Tailscale's
  100.64.0.0/10, written as IP addresses (a DNS name never counts: it could resolve anywhere).
  #25's https rule broke the LAN gateways (#26), and then Tailscale, because Python's
  `is_private` does not cover 100.64.0.0/10 (#27). Any change to URL checks must keep all three working.

## Security invariants
- A cashier can read the PosAPI record and every order. Nothing reachable over RPC may send the
  gateway key, issue or void a bill, or reset the sending status (#11, #25; `test_security`).
- `EBARIMT_PROTECTED_FIELDS` (`pos_ebarimt/models/pos_order.py`) are dropped on create and
  refused on write for anyone but the superuser. A new sending-state field goes in that set (#25, #29).
- Never log customer TINs, config JSON, lottery numbers or QR data (#25). Unexpected errors shown
  to users carry the exception type only.
- A refund finds the bill it voids from the refund itself (`refunded_order_id`, else its lines'
  `refunded_orderline_id`), never by searching for a likely sale: a guessed match once voided
  another sale's bill (smb-pos-dev F4).

<!-- agent-brain:begin. Generated from projects/claude-md-block.md in Ariyajav/agent-brain by bin/subprojects.py block. Edit it there, not here. -->
## agent-brain: how this repo feeds back

This repo is a sub-project of agent-brain (github.com/Ariyajav/agent-brain), which learns from it. Every night agent-brain reads the pull requests merged here and the trailers on their commits, and its Mentor turns repeated friction into rules. You don't need access to agent-brain. Your part is three habits.

1. **Say what you verified, in every commit.** Put a `Verified:` trailer on its own line just above `Co-Authored-By:`: the command you ran and its result, or what couldn't run and why. For example `Verified: make check: 98 passed`, or `Verified: py_compile only; the test suite did not run (no database here)`. Never claim a check you didn't run. A commit without the trailer counts as unverified.
2. **Leave one lesson when something went wrong.** If you redid work, fixed something a recent PR broke, or a guess about an outside system turned out wrong, add one `Agent-Lesson:` trailer: a single imperative sentence about how to work, not about this codebase. Leave it out when nothing went wrong.
3. **Keep facts here, send habits up.** Facts about this code or the systems it talks to (field names, enum values, limits, how it is deployed) go into this CLAUDE.md, in the same pull request that taught you them. Habits that would help in any repo go in the `Agent-Lesson:` trailer.

### Rules from agent-brain's lessons.md
- Check repo and system state with a fresh command before you state it; what you remember may be stale. (2026-07-07)
- Take an outside API's field names, enum values and limits from its spec or a real response, and cite the source in the commit; never infer them from names. (2026-11-05)
- Before adding a check that refuses something that worked before (validation, hardening), list the setups actually in use and test the check against each one. (2026-11-05)
- When you fix a bug that a recent PR introduced, put the regression test in the same PR. (2026-11-05)
- Tests you couldn't run haven't passed: say so in the `Verified:` trailer and the PR description, and let CI run them before merge. (2026-11-05)
- Make dev and CI fail the way production would: the same roles and permissions, log levels, file modes and network paths. Whatever only production has, you can't see until it ships. (2026-11-05)
- Treat the first run on a host you can't reach as a test: a dry-run or plan mode, its assumptions about the host written down, and logs that let someone fix it from the log alone. (2026-11-05)
- A feature ships with the path a user takes to reach it, and a test that walks that path. (2026-11-05)
- Never leave a hand fix on a host: copy it back to the repo and through the normal gate the same day. (2026-11-05)
- Before deleting a branch, retarget the open PRs based on it; GitHub closes them for good when their base disappears. (2026-11-05)
- When a change touches several files or components, run the whole test suite, not only the tests next to the change. (2026-07-10)
- When a reviewer proposes a code change, check it against the library's documentation before adopting it; the diagnosis can be right and the fix wrong. (2026-07-10)
- When a reviewer flags a possible bug you think is by design, run the scenario before dismissing it. (2026-07-08)
- A claim that something is missing is itself a claim to check: search the code before building it. (2026-07-11)
- A commit message describes everything the commit carries: run `git status` before committing. (2026-07-11)
- Minimal means no unrequested code, never fewer tests, error handling, input validation or safety checks. (2026-07-10)
- If a tool result is unreadable, say you can't verify it; never describe output from memory. (2026-07-08)
<!-- agent-brain:end -->
