#!/bin/sh
# Second local instance for the setter-stability audit (port 7902) so it can
# run alongside another session's 7901 dev server. Same flags as run-signals-dev;
# DELIV_MOCK enables /api/_mock/dev-login for rendered-UI verification (the
# setter tab reads REAL Supabase data either way).
cd "$HOME/navreo-signals" || exit 1
export NAVREO_NO_BG=1
export DELIV_MOCK=1
exec python3 app/server.py 7902
