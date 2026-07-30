#!/bin/sh
# Second local instance for the setter-stability audit (port 7902) so it can
# run alongside another session's 7901 dev server. Same flags as run-signals-dev.
cd "$HOME/navreo-signals" || exit 1
export NAVREO_NO_BG=1
exec python3 app/server.py 7902
