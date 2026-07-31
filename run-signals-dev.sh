#!/bin/sh
# Local dev run of the signals server for UI verification.
# NAVREO_NO_BG disables background pullers/cron; DELIV_MOCK serves mock
# deliverability data. /api/collisions still reads live Supabase via sb().
cd "$HOME/navreo-signals" || exit 1
export NAVREO_NO_BG=1
export DELIV_MOCK=1
exec python3 app/server.py 7901
