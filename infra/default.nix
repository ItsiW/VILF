{
  perSystem = {nix, ...}:
    with nix; {
      packages.sops = pkgs.sops;
      canivete.opentofu.workspaces.main = {
        plugins = ["opentofu/google" "opentofu/random" "integrations/github"];
        modules.main = {config, ...}: {
          imports = [./dns.nix ./server.nix ./certificate.nix ./bucket.nix ./network.nix];
          options.google.services = mkOption {
            type = listOf str;
            default = [];
            description = mdDoc "Service APIs to enable in the project";
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
