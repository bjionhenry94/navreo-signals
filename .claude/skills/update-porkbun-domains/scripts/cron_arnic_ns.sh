#!/bin/bash
set -u

SKILL_DIR="$HOME/.claude/skills/update-porkbun-domains"
CSV="$SKILL_DIR/arnic_dnsimple.csv"
LOG="$SKILL_DIR/logs/arnic_ns.log"

if [ -f "$HOME/.navreo-keys.env" ]; then
  set -a
  . "$HOME/.navreo-keys.env"
  set +a
fi

if [ -z "${PORKBUN_API_KEY:-}" ] || [ -z "${PORKBUN_SECRET_API_KEY:-}" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] ABORT: Porkbun keys not set" >> "$LOG"
  exit 1
fi

echo "" >> "$LOG"
echo "=== [$(date '+%Y-%m-%d %H:%M:%S %z')] arnic NS sync start ===" >> "$LOG"
/Library/Frameworks/Python.framework/Versions/3.10/bin/python3 "$SKILL_DIR/scripts/bulk_update_porkbun_ns.py" "$CSV" >> "$LOG" 2>&1
echo "=== [$(date '+%Y-%m-%d %H:%M:%S %z')] arnic NS sync end (exit=$?) ===" >> "$LOG"
