#! /usr/bin/env bash
config=${config:-$(nix --extra-experimental-features "nix-command flakes" build .#terranix --print-out-paths)}
workspace=$(git rev-parse --show-toplevel)/infra
cp -fL "$config" "$workspace/main.tf.json"
tofu "-chdir=$workspace" "$@"
