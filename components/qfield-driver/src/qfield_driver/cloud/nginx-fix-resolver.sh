#!/bin/sh
# Point nginx at the runtime's DNS, docker uses 127.0.0.11 and podman the network gateway.
NS=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf)
grep -rl 'resolver 127.0.0.11' /etc/nginx/templates | while read -r f; do
  sed -i "s/resolver 127.0.0.11/resolver $NS/" "$f"
done
exec /docker-entrypoint.sh nginx -g 'daemon off;'
