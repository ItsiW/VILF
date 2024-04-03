{
  description = "Vegans In Love with Food";
  inputs = {
    canivete.url = github:schradert/canivete;
    nixpkgs.follows = "canivete/nixpkgs";
    nixpkgs-stable.follows = "canivete/nixpkgs-stable";
    flake-parts.follows = "canivete/flake-parts";
    pre-commit.follows = "canivete/pre-commit";
    systems.follows = "canivete/systems";
    opentofu-registry.follows = "canivete/opentofu-registry";

    terranix.url = github:terranix/terranix;
    terranix.inputs.nixpkgs.follows = "nixpkgs";

    nix2container.url = github:nlewo/nix2container;
    nix2container.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs = inputs:
    with inputs;
      flake-parts.lib.mkFlake {inherit inputs;} {
        imports = [canivete.flakeModules.default ./infra];
        systems = import systems;
        perSystem = {
          pkgs,
          self',
          ...
        }: {
          packages.default = pkgs.writeShellApplication {
            name = "vilf";
            excludeShellChecks = ["SC2015"];
            text = ''
              nixCmd() { nix --extra-experimental-features "nix-command flakes" "$@"; }
              [[ -z ''${1-} || $1 == default ]] && nixCmd flake show || nixCmd run ".#$1" -- "''${@:2}"
            '';
          };
          devShells.cli = pkgs.mkShell {
            packages = [self'.packages.default];
          };
        };
      };
}
