{
  config,
  inputs,
  inputs',
  lib,
  pkgs,
  ...
}: let
  # TODO figure out if opentofu provider outputs url
  # name =
  #   with config.resource.google_artifact_registry_repository.main;
  #   "${location}-${lib.strings.toLower format}.pkg.dev/${project}/${repository_id}/function";
  name = "localhost/server";
  tag = "0.0.1";
  deploy = pkgs.writeShellApplication {
    name = "deploy";
    runtimeInputs = with pkgs; [git google-cloud-sdk jq postgresql python312];
    text = builtins.readFile ./deploy.sh;
  };
  server = let
    libraries = with pkgs.python3Packages; lib.concat [fastapi uvicorn] uvicorn.optional-dependencies.standard;
  in
    pkgs.writers.writePython3 "serve" {inherit libraries;} (builtins.readFile ./server.py);
  container = with inputs'.nix2container.packages.nix2container;
    buildImage {
      inherit name tag;
      layers = [
        (buildLayer {deps = [server];})
        (buildLayer {deps = [deploy];})
      ];
      config.entrypoint = ["${server}/bin/uvicorn" "${server}/bin/main:app" "--reload"];
    };
in {
  # resource.google_project_service.artifacts.service = "artifactregistry.googleapis.com";
  # resource.google_artifact_registry_repository.main = {
  #   depends_on = ["google_project_service.artifacts"];
  #   repository_id = "main";
  #   format = "DOCKER";
  #   location = config.provider.google.region;
  #   project = config.provider.google.project;
  # };
  # resource.null_resource.container = {
  #   triggers = {inherit name tag;};
  #   provisioner.local-exec.command = lib.getExe container.copyToPodman;
  # };
  # resource.google_project_service.run.service = "run.googleapis.com";
  # resource.google_cloud_run_v2_service.main = {
  #   depends_on = ["google_project_service.run"];
  #   name = "main";
  #   location = config.provider.google.region;
  #   template.containers.image = "${name}:${tag}";
  #   template.containers.env = lib.attrsets.mapAttrsToList lib.nameValuePair {
  #     VILF_GIT_BRANCH = "develop";
  #     VILF_GIT_URL = "https://github.com/ItsiW/VILF.git";
  #     VILF_PG_USER = "\${ google_sql_user.appsmith.name }";
  #     VILF_PG_HOST = "\${ google_sql_database_instance.main.public_ip_address }";
  #     VILF_PG_DB = "\${ google_sql_database.appsmith.name }";
  #     VILF_PG_TABLE = "submission";
  #     VILF_GCS_BUCKET = "\${ google_storage_bucket.main.url }";
  #     VILF_DEPLOY = toString deploy;
  #   };
  # };
}
