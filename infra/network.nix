{
  google.services = ["compute"];
  resource = {
    google_compute_url_map.main = {
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
    google_compute_global_address.main = {
      depends_on = ["google_project_service.compute"];
      name = "vilf-lb-ipv4";
    };
    google_compute_global_forwarding_rule.http = {
      name = "vilf-lb-http-frontend";
      ip_address = "\${ google_compute_global_address.main.address }";
      target = "\${ google_compute_target_http_proxy.main.id }";
      port_range = "80-80";
    };
    google_compute_global_forwarding_rule.https = {
      name = "vilf-lb-https-frontend";
      ip_address = "\${ google_compute_global_address.main.address }";
      target = "\${ google_compute_target_https_proxy.main.id }";
      port_range = "443-443";
    };
  };
}
