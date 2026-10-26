#!/usr/bin/env bash
# Shortcut for the one-command deploy: ./deploy.sh [--status|--dry-run|--force|...] runs deploy/deploy.sh.
# See docs/deploy.md.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy/deploy.sh" "$@"
