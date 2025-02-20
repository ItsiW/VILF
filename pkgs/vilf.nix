{
  lib,
  stdenv,
  libjpeg,
  python310,
  zlib,
}: let
  python = python310.withPackages (ps:
    with ps; [
      click
      pyyaml
      jinja2
      markdown2
      mdplain
      pillow
      tqdm
      selenium
      unidecode
      webdriver-manager
    ]);
in
  stdenv.mkDerivation {
    name = "vilf";
    src = lib.sourceByRegex ./. ["^(raw|html|places|static|scripts)(/.*)?$" "^about\\.md$"];
    nativeBuildInputs = [libjpeg.dev zlib.dev python];
    buildPhase = "python3 -m scripts.cli build";
    installPhase = "cp -R build $out";
  }
