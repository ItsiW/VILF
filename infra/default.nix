{
  perSystem = {nix, ...}:
    with nix; {
      packages.sops = pkgs.sops;
      canivete.opentofu.workspaces.main = {
        plugins = ["opentofu/google" "opentofu/random" "integrations/github"];
        modules.main = {
          imports = [./dns.nix ./server.nix ./certificate.nix ./database.nix ./bucket.nix ./network.nix];
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
            # TODO extract this into each module with an option
            google_project_service = genAttrs ["certificatemanager" "compute" "storage" "sqladmin" "dns"] (name: {
              depends_on = ["google_billing_project_info.main" "data.google_project_service.serviceusage" "data.google_project_service.cloudresourcemanager"];
              service = "${name}.googleapis.com";
            });

            # google_service_account.vilfer.account_id = "vilfer";
            # google_service_account_key.vilfer.service_account_id = "\${ google_service_account.vilfer.name }";
            # github_actions_secret.VILF_SA_CREDS = {
            #   repository = "VILF";
            #   secret_name = "VILF_SA_CREDS";
            #   encrypted_value = "\${ google_service_account_key.vilfer.private_key }";
            # };
          };
        };
      };
    };
}
