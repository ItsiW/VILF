{
  perSystem = {nix, ...}:
    with nix; {
      canivete.opentofu.workspaces.new = {
        plugins = ["opentofu/google" "opentofu/random" "integrations/github"];
        modules.main = {
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
            google_project_service = genAttrs ["certificatemanager" "compute" "storage" "sqladmin"] (name: {
              depends_on = ["google_billing_project_info.main" "data.google_project_service.serviceusage" "data.google_project_service.cloudresourcemanager"];
              service = "${name}.googleapis.com";
            });
            google_storage_bucket.main = {
              depends_on = ["google_project_service.storage"];
              name = "vilf-org";
              location = "US";
            };
            google_certificate_manager_certificate_map.main = {
              depends_on = ["google_project_service.certificatemanager"];
              name = "vilf-map";
            };
            google_compute_backend_bucket.main = rec {
              depends_on = ["google_project_service.compute"];
              name = bucket_name;
              bucket_name = "\${ google_storage_bucket.main.name }";
              enable_cdn = true;
              compression_mode = "DISABLED";
              custom_response_headers = ["Strict-Transport-Security:max-age=31536000; includeSubDomains; preload"];
            };
            google_compute_url_map.main = {
              depends_on = ["google_project_service.compute"];
              name = "vilf-lb";
              default_service = "\${ google_compute_backend_bucket.main.id }";
            };
            google_compute_url_map.redirect = {
              depends_on = ["google_project_service.compute"];
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
              depends_on = ["google_project_service.compute"];
              name = "vilf-lb-http-proxy";
              url_map = "\${ google_compute_url_map.redirect.id }";
            };
            google_compute_target_https_proxy.main = {
              depends_on = ["google_project_service.compute"];
              name = "vilf-lb-https-proxy";
              url_map = "\${ google_compute_url_map.main.id }";
              certificate_map = "https://certificatemanager.googleapis.com/v1/\${ google_certificate_manager_certificate_map.main.id }";
            };
            google_compute_global_forwarding_rule.http = {
              depends_on = ["google_project_service.compute"];
              name = "vilf-lb-http-frontend";
              target = "\${ google_compute_target_http_proxy.main.id }";
              port_range = "80-80";
            };
            google_compute_global_forwarding_rule.https = {
              depends_on = ["google_project_service.compute"];
              name = "vilf-lb-https-frontend";
              target = "\${ google_compute_target_https_proxy.main.id }";
              port_range = "443-443";
            };

            google_sql_database_instance.main = {
              depends_on = ["google_project_service.sqladmin"];
              name = "vilf";
              database_version = "POSTGRES_15";
              settings = {
                deletion_protection_enabled = true;
                tier = "db-custom-2-8192";
                ip_configuration.authorized_networks = mapAttrsToList nameValuePair {
                  appsmith-1 = "18.223.74.85";
                  appsmith-2 = "3.131.104.27";
                };
              };
            };
            google_sql_database.appsmith = {
              depends_on = ["google_project_service.sqladmin"];
              name = "appsmith";
              instance = "\${ google_sql_database_instance.main.name }";
            };
            random_password.appsmith.length = 21;
            google_sql_user.appsmith = {
              depends_on = ["google_project_service.sqladmin"];
              name = "appsmith";
              instance = "\${ google_sql_database_instance.main.name }";
              password = "\${ random_password.appsmith.result }";
            };

            # google_service_account.github.account_id = "github";
            # google_service_account_key.github.service_account_id = "\${ google_service_account.github.name }";
            # github_actions_secret.VILF_SA_CREDS = {
            #   repository = "VILF";
            #   secret_name = "VILF_SA_CREDS";
            #   encrypted_value = "\${ google_service_account_key.github.private_key }";
            # };
          };
        };
      };
    };
}
