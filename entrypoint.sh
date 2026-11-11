#!/bin/sh
# Start as root only to fix ownership of a bind-mounted data folder, then drop to the unprivileged user.
# If the container is started as another user (compose "user:"), just run the command.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$(dirname "${DB_PATH:-/data/macrolog.db}")"
    chown -R 10001:10001 "$(dirname "${DB_PATH:-/data/macrolog.db}")"
    exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi
exec "$@"
