#!/bin/sh
set -e

echo "tunneluser:${TUNNEL_PASSWORD:-tunnelpass}" | chpasswd

exec /usr/sbin/sshd -D -e
