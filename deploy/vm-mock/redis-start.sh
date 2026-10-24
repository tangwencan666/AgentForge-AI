#!/bin/sh
set -eu
test "${#VM_MOCK_REDIS_PASSWORD}" -eq 64
case "$VM_MOCK_REDIS_PASSWORD" in *[!0-9a-f]*) exit 1;; esac
umask 077
{
    printf 'bind 0.0.0.0\nprotected-mode yes\nport 6379\n'
    printf 'requirepass %s\n' "$VM_MOCK_REDIS_PASSWORD"
    printf 'dir /data\nappendonly yes\nmaxmemory 64mb\nmaxmemory-policy noeviction\n'
} > /tmp/vm-mock-redis.conf
chown redis:redis /tmp/vm-mock-redis.conf
exec /usr/local/bin/docker-entrypoint.sh redis-server /tmp/vm-mock-redis.conf
