#!/usr/bin/env bash

if [[ -n $ADC ]]; then
    auth_check_args=(application-default print-access-token)
else
    auth_check_args=(list --filter status:ACTIVE --format "value(ACCOUNT)")
fi

if ! gcloud auth "${auth_check_args[@]}" &>/dev/null; then
    gum log --level warn "No account authenticated with gcloud. Authenticating with Google APIs now..."
    gcloud auth "${ADC:+application-default}" login
fi
