#!/bin/sh
# Render the nginx config from its template, substituting only our own
# variables so nginx's runtime variables ($host, $uri, $request_id, ...) are
# left intact. Defaults keep `docker compose up` working unchanged.
set -e

export PORT="${PORT:-80}"
export BACKEND_URL="${BACKEND_URL:-http://api:8000}"

envsubst '${PORT} ${BACKEND_URL}' \
    < /etc/nginx/templates/default.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
