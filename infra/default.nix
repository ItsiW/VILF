{
  imports = [./new.nix];
  perSystem = {
    nix,
    pkgs,
    ...
  }: {
    packages.sops = pkgs.sops;
    canivete.opentofu.workspaces.main = {
      plugins = ["opentofu/google" "opentofu/null"];
      modules.main = {config, ...}: {
        imports = [./server.nix];
        provider.google = {
          project = "climax-vilf";
          region = "us-west1";
          zone = "us-west1-b";
          billing_project = "climax-billing";
        };
        data.google_organization.main.domain = "climaxfoods.com";
        data.google_billing_account.main.display_name = "Climax Foods Inc. - SADA";
        resource = {
          google_project.main = rec {
            project_id = config.provider.google.project;
            name = project_id;
            org_id = "\${ data.google_organization.main.org_id }";
            billing_account = "\${ data.google_billing_account.main.id }";
          };
          google_storage_bucket.main = {
            name = "climax-vilf-bucket";
            location = "US";
          };
          google_certificate_manager_certificate_map.main = {
            name = "vilf-map";
          };
          google_compute_backend_bucket.main = rec {
            name = bucket_name;
            bucket_name = "\${ google_storage_bucket.main.name }";
            enable_cdn = true;
            compression_mode = "DISABLED";
            custom_response_headers = ["Strict-Transport-Security:max-age=31536000; includeSubDomains; preload"];
          };
          google_compute_url_map.main = {
            name = "vilf-lb";
            default_service = "\${ google_compute_backend_bucket.main.id }";
          };
          google_compute_url_map.redirect = {
            name = "vilf-redirect";
            default_url_redirect = {
              https_redirect = true;
              redirect_response_code = "MOVED_PERMANENTLY_DEFAULT";
              strip_query = false;
            };
            # TODO why are blank services required here but don't do anything?
            # TODO do I need expectedOutputUrl and expectedRedirectResponseCode?
            test = [
              {
                description = "Test with no query parameters";
                host = "vilf.org";
                path = "/best/";
                service = "";
              }
              {
                description = "Test with query parameters";
                host = "vilf.org";
                path = "/best/?parameter1=value1&parameter2=value2";
                service = "";
              }
            ];
          };
          google_compute_target_http_proxy.main = {
            name = "vilf-lb-http-proxy";
            url_map = "\${ google_compute_url_map.redirect.id }";
          };
          google_compute_target_https_proxy.main = {
            name = "vilf-lb-https-proxy";
            url_map = "\${ google_compute_url_map.main.id }";
            certificate_map = "https://certificatemanager.googleapis.com/v1/\${ google_certificate_manager_certificate_map.main.id }";
          };
          google_compute_global_forwarding_rule.http = {
            name = "vilf-lb-http-frontend";
            target = "\${ google_compute_target_http_proxy.main.id }";
            port_range = "80-80";
          };
          google_compute_global_forwarding_rule.https = {
            name = "vilf-lb-https-frontend";
            target = "\${ google_compute_target_https_proxy.main.id }";
            port_range = "443-443";
          };
          google_sql_database_instance.main = {
            name = "vilf";
            database_version = "POSTGRES_15";
            settings = {
              deletion_protection_enabled = true;
              tier = "db-custom-2-8192";
              ip_configuration.authorized_networks = nix.mapAttrsToList nix.nameValuePair {
                appsmith-1 = "18.223.74.85";
                appsmith-2 = "3.131.104.27";
              };
            };
          };
          google_sql_database.appsmith = {
            name = "appsmith";
            instance = "\${ google_sql_database_instance.main.name }";
          };
          google_sql_user.appsmith = {
            name = "appsmith";
            instance = "\${ google_sql_database_instance.main.name }";
          };
        };
      };
    };
  };
}
