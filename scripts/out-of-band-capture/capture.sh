#!/usr/bin/env bash
# Capture one host's half of the out-of-band deployment check, and write a
# dated, self-hashing transcript. Run on the host itself, over SSH.
#
#   sh capture.sh gate  <GATE_HOST_IP>
#   sh capture.sh agent <GATE_HOST_IP>
#
# Exits 0 only when every expectation for that role holds. A failed expectation
# still writes the transcript, so the record shows what was true, not what was
# hoped for.
set -u

ROLE="${1:-}"
GATE_IP="${2:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="out-of-band-${STAMP}-${ROLE:-unknown}.txt"

if [ -z "$ROLE" ] || [ -z "$GATE_IP" ]; then
  echo "usage: sh capture.sh <gate|agent> <GATE_HOST_IP>" >&2
  exit 2
fi

fail=0
say() { printf '%s\n' "$*" | tee -a "$OUT"; }
run() { # run <label> <expect:ok|refuse> <command...>
  label="$1"; expect="$2"; shift 2
  say ""
  say "### $label"
  say "\$ $*"
  out="$("$@" 2>&1)"; rc=$?
  say "$out"
  say "[exit $rc; expected $expect]"
  if [ "$expect" = "refuse" ] && [ "$rc" -eq 0 ]; then
    say "!!! UNEXPECTED: command succeeded where refusal was required"
    fail=1
  fi
  if [ "$expect" = "ok" ] && [ "$rc" -ne 0 ]; then
    say "!!! UNEXPECTED: command failed where success was required"
    fail=1
  fi
}

: > "$OUT"
say "# Out-of-band deployment check, captured transcript"
say "role: $ROLE"
say "gate_host: $GATE_IP"
say "captured_utc: $STAMP"
say "hostname: $(hostname 2>/dev/null || echo unknown)"
say "uname: $(uname -a 2>/dev/null)"
say "whoami: $(whoami 2>/dev/null)"
say "NOTE: this transcript records what the host reported at the time above."
say "NOTE: it is not a claim that the pattern is complete, only that these checks held."

say ""
say "## Firewall state"
run "ufw status" ok ufw status verbose

case "$ROLE" in
  gate)
    say ""
    say "## Gate reachable from itself"
    run "gate health" ok curl -sS --max-time 5 "https://localhost/health"
    say ""
    say "## Containers"
    run "docker ps" ok docker ps --format "{{.Names}} {{.Status}}"
    say ""
    say "## Fail-closed check: stop the gate, the next action must be refused"
    say "Run manually and paste the result:"
    say "  docker compose stop custos && curl -sS --max-time 5 https://localhost/health"
    say "  (an unreachable gate is the expected outcome; record the exact output)"
    ;;
  agent)
    say ""
    say "## Gate reachable from the agent host"
    run "gate health" ok curl -sS --max-time 5 "https://${GATE_IP}/health"
    say ""
    say "## Open internet must be denied"
    run "internet egress" refuse curl -sS --max-time 5 https://example.com
    run "second internet target" refuse curl -sS --max-time 5 https://1.1.1.1
    say ""
    say "## Listening sockets (should carry nothing world-facing)"
    run "ss -lntu" ok ss -lntu
    ;;
  *)
    say "!! unknown role '$ROLE'"
    fail=1
    ;;
esac

say ""
if [ "$fail" -eq 0 ]; then
  say "RESULT: all expectations held"
else
  say "RESULT: at least one expectation did NOT hold (see !!! lines)"
fi
say "FILE: $OUT"

# The hash must cover the RESULT line, or a reader cannot rely on the verdict.
# Everything above this marker is hashed; nothing is written after it.
say ""
sum="$(sha256sum "$OUT" | awk '{print $1}')"
say "## Self-hash"
say "sha256(before this line): $sum"
exit "$fail"
