{
  perSystem = {
    config,
    lib,
    pkgs,
    self',
    ...
  }: let
    inherit (lib) genAttrs getExe mkOption readFile types;
    auth-gcp = pkgs.writeShellApplication {
      name = "auth-gcp";
      runtimeInputs = with pkgs; [google-cloud-sdk gum];
      text = ''
        if [[ -n $ADC ]]; then
            auth_check_args=(application-default print-access-token)
        else
            auth_check_args=(list --filter status:ACTIVE --format "value(ACCOUNT)")
        fi

        if ! gcloud auth "''${auth_check_args[@]}" &>/dev/null; then
            gum log --level warn "No account authenticated with gcloud. Authenticating with Google APIs now..."
            gcloud auth ''${ADC:+application-default} login
        fi
      '';
    };
    auth-gcp-adc = pkgs.wrapFlags auth-gcp "--set ADC 1";
    auth-github = pkgs.writeShellApplication {
      name = "auth-github";
      runtimeInputs = with pkgs; [gh gum];
      text = ''
        if ! gh auth status &>/dev/null; then
            gum log --level warn "No account authenticated with gh. Authenticating with GitHub APIs now..."
            gh auth login
        fi
      '';
    };
    deploy = pkgs.writeShellApplication {
      name = "deploy";
      runtimeInputs = with pkgs; [yq google-cloud-sdk gum];
      runtimeEnv = let
        inherit (config.canivete.opentofu.workspaces.main.composition.config) resource;
      in {
        BUCKET = resource.google_storage_bucket.main.name;
        DIRECTORY = "build";
        URL_MAP = resource.google_compute_url_map.main.name;
      };
      text = readFile ./deploy-nix.sh;
    };
  in {
    apps.default = self'.apps.tofu;
    apps.tofu = {
      type = "app";
      program = getExe (pkgs.wrapFlags config.canivete.opentofu.script "--run \"${getExe auth-gcp-adc}\" --run \"${getExe auth-github}\" --add-flags \"--workspace main\"");
      meta.description = "Deploy infrastructure (wrapper around OpenTofu CLI)";
    };
    apps.deploy = {
      type = "app";
      program = getExe deploy;
      meta.description = "Update static files in production";
    };
    canivete.devShells.shells.default.packages = with pkgs; [gh google-cloud-sdk];
    canivete.just.recipes.deploy = getExe (pkgs.wrapFlags deploy "--run \"${getExe auth-gcp}\"");
    canivete.opentofu.workspaces.main = {
      plugins = ["opentofu/google" "opentofu/random" "integrations/github"];
      modules.main = {config, ...}: {
        imports = [./dns.nix ./server.nix ./certificate.nix ./bucket.nix ./network.nix];
        options.google.services = mkOption {
          type = types.listOf types.str;
          default = [];
          description = "Service APIs to enable in the project";
        };
        config = {
          provider.google = {
            project = "vilf-com";
            region = "us-west1";
            zone = "us-west1-b";
          };
          provider.github.owner = "ItsiW";
          data = {
            google_billing_account.main.display_name = "My Billing Account";
            # Setting the quota project requires these enabled service APIs
            google_project_service.cloudresourcemanager.service = "cloudresourcemanager.googleapis.com";
            google_project_service.serviceusage.service = "serviceusage.googleapis.com";
          };
          resource = {
            google_billing_project_info.main.billing_account = "\${ data.google_billing_account.main.id }";
            google_project_service = genAttrs config.google.services (name: {
              depends_on = ["google_billing_project_info.main" "data.google_project_service.serviceusage" "data.google_project_service.cloudresourcemanager"];
              service = "${name}.googleapis.com";
            });
            google_service_account.vilfer.account_id = "vilfer";
            google_service_account_key.vilfer.service_account_id = "\${ google_service_account.vilfer.name }";
            github_actions_secret.VILF_CREDS = {
              repository = "VILF";
              secret_name = "VILF_CREDS";
              plaintext_value = "\${ google_service_account_key.vilfer.private_key }";
            };
          };
        };
      };
    };
  };
}
