#!/bin/sh
# Keep upstream Docker-in-Docker setup; add only explicitly requested settings.
set -eu
if [ -n "${VERIFIER_REGISTRY_MIRROR:-}" ]; then
    set -- "$@" "--registry-mirror=$VERIFIER_REGISTRY_MIRROR"
fi
if [ -n "${VERIFIER_DNS:-}" ]; then
    set -- "$@" "--dns=$VERIFIER_DNS"
    if [ -n "${VERIFIER_DNS_FALLBACK:-}" ]; then
        set -- "$@" "--dns=$VERIFIER_DNS_FALLBACK"
    fi
fi
exec dockerd-entrypoint.sh "$@"
