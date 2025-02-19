# Infrastructure

We use [OpenTofu](https://opentofu.org/) to track infrastructure declaratively. Configuration is not defined in HCL but rather in [Nix](https://nixos.org) through the repository framework [Canivete](https://github.com/schradert/canivete), which provides an abstraction around [Terranix](https://github.com/terranix/terranix).

## Getting Started

### Nix

Building Nix closures requires an active installation of the [Nix package manager](https://nixos.org/download).

For convenience, be sure to enable the not-so-experimental "experimental features" [`nix-command flakes`](https://nix.dev/manual/nix/latest/command-ref/conf-file).

Furthermore, to facilitate development on this project, not just for infrastructure scripts but also SSG tooling and `pre-commit` hooks for linting and autoformat, a development shell is provided. This can be accessed either by running `nix develop` in the project root every time, or preferably using `direnv` + the `nix-direnv` adapter to handle that automatically with better system integration. With `nix` installed, you can install these tools easily with `nix profile install nixpkgs#direnv nixpkgs#nix-direnv`.

### SOPS

Deploying infrastructure currently requires three levels of authentication: GitHub, Google, and OpenTofu. The first two are handled programmatically through the deployment script, but managing OpenTofu state requires access to an encryption password. This password is obscured [in the repository](../.canivete/sops/default.yaml) with [SOPS](https://github.com/getsops/sops).

To gain access, run `just sops-setup -n vilf` in the development shell. This will create two asymmetric keypairs stored on your system (under `$HOME/.ssh` and `$XDG_CONFIG_HOME/sops`) that will need to be copied to other devices you use for development. Add the listed public key to `.sops.yaml` where relevant and contact one of the other developers with a key already saved to run `sops updatekeys .canivete/sops/default.yaml` in order to authorize your key for secret management in the repository.

## Usage

### OpenTofu

```bash
nix run . <opentofu args>
```

### Invalidate Cloud CDN cache

```bash
# Requires roles/owner on projects/vilf-com
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path "/*"
```
