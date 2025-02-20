{
  lib,
  buildPythonPackage,
  fetchFromGitHub,
  beautifulsoup4,
  markdown,
  setuptools,
}:
buildPythonPackage {
  pname = "mdplain";
  version = "1.0";
  src = fetchFromGitHub {
    owner = "icaijy";
    repo = "mdplain";
    rev = "5953c3a4c65e4b3df57b34b12446f6a60b3dfd2c";
    hash = "sha256-y9e6z092422PQyDSQp4SLrKawLMRUzdjw3/IZELrbCY=";
  };
  meta.license = lib.licenses.mit;

  build-system = [setuptools];
  dependencies = [beautifulsoup4 markdown];
}
