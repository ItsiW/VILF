#!/usr/bin/env bash

if ! gh auth status &>/dev/null; then
    gum log --level warn "No account authenticated with gh. Authenticating with GitHub APIs now..."
    gh auth login
fi
