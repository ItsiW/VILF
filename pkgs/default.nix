{
  flake.overlays.default = final: prev: {
    vilf = final.callPackage ./vilf.nix {};
    pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [(pyfinal: _: {mdplain = pyfinal.callPackage ./mdplain.nix {};})];
  };
  perSystem = {pkgs, ...}: {packages.default = pkgs.vilf;};
}
