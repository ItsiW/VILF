{nix, ...}:
with nix; let
  domain = "vilf.org";
in {
  resource = {
    google_certificate_manager_dns_authorization = mapAttrs (_: cfg:
      mergeAttrs cfg {
        depends_on = ["google_project_service.certificatemanager"];
        name = replaceStrings ["."] ["-"] cfg.domain;
      }) {
      root = {inherit domain;};
      www.domain = "www.${domain}";
    };
    google_certificate_manager_certificate.main = {
      name = "vilf-org";
      managed.domains = [domain "www.${domain}"];
      managed.dns_authorizations = [
        "\${ google_certificate_manager_dns_authorization.root.id }"
        "\${ google_certificate_manager_dns_authorization.www.id }"
      ];
    };
    google_certificate_manager_certificate_map.main = {
      depends_on = ["google_project_service.certificatemanager"];
      name = "vilf-map";
    };
    google_certificate_manager_certificate_map_entry.main = {
      name = "vilf-org";
      map = "\${ google_certificate_manager_certificate_map.main.name }";
      certificates = ["\${ google_certificate_manager_certificate.main.id }"];
      matcher = "PRIMARY";
    };
  };
}
