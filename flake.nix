{
  description = "Vegans In Love with Food";
  inputs = {
    canivete.url = github:schradert/canivete;
    nix2container.url = github:nlewo/nix2container;
    nix2container.inputs.nixpkgs.follows = "canivete/nixpkgs";
  };
  outputs = inputs:
    inputs.canivete.lib.mkFlake {inherit inputs;} [] {
      imports = [./infra];
      perSystem.canivete = {
        sops.enable = true;
        # TODO implement pre-commit across entire repo
        pre-commit.languages.shell.enable = true;
        pre-commit.settings = {
          excludes = ["static" "scripts" "raw" "places" "html"];
          hooks.no-commit-to-branch.settings.branch = ["develop"];
          hooks.lychee.settings.flags = "--exclude googleapis";
          hooks.markdownlint.settings.configuration = {
            MD013.line_length = -1;
            MD033.allowed_elements = ["span"];
          };
        };
      };
    };
}
