{
  description = "Vegans In Love with Food";
  inputs = {
    canivete.url = github:schradert/canivete;
    nix2container.url = github:nlewo/nix2container;
    nix2container.inputs.nixpkgs.follows = "canivete/nixpkgs";
  };
  outputs = inputs: inputs.canivete.lib.mkFlake {inherit inputs;} {imports = [./infra];};
}
