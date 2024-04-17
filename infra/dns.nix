{nix, ...}:
with nix; let
  domain = "vilf.org";
  dns_name = "${domain}.";
in {
  google.services = ["dns"];
  resource.google_dns_managed_zone.main = {
    depends_on = ["google_project_service.dns"];
    name = "vilf-org";
    inherit dns_name;
  };
  resource.google_dns_record_set = let
    common_args = {
      managed_zone = "\${ google_dns_managed_zone.main.name }";
      ttl = 300;
    };
    # TODO why can't I reference 'config' here without getting infinite recursion
    records.certificates = listToAttrs (forEach ["root" "www"] (name:
      nameValuePair "_acme-challenge_${name}" {
        name = "\${ google_certificate_manager_dns_authorization.${name}.dns_resource_record[0].name }";
        type = "\${ google_certificate_manager_dns_authorization.${name}.dns_resource_record[0].type }";
        rrdatas = ["\${ google_certificate_manager_dns_authorization.${name}.dns_resource_record[0].data }"];
      }));
    records.fastmail = listToAttrs (forEach (range 1 3) (n: let
      prefix = "fm${toString n}._domainkey";

      name = "${prefix}.${dns_name}";
      type = "CNAME";
      rrdatas = ["fm${toString n}.${domain}.dkim.fmhosted.com."];

      key = replaceStrings ["."] ["_"] prefix + "_c";
    in
      nameValuePair key {inherit name type rrdatas;}));
    records.manual = {
      www-a = {
        name = "www.${dns_name}";
        type = "A";
        rrdatas = ["\${ google_compute_global_address.main.address }"];
      };
      root-a = {
        name = dns_name;
        type = "A";
        rrdatas = ["\${ google_compute_global_address.main.address }"];
      };
      root-caa = {
        name = dns_name;
        type = "CAA";
        rrdatas = ["0 issue \"pki.goog\"" "0 issue \"letsencrypt.org\""];
      };
      root-mx = {
        name = dns_name;
        type = "MX";
        rrdatas = [
          "10 in1-smtp.messagingengine.com."
          "20 in2-smtp.messagingengine.com."
        ];
      };
      root-txt = {
        name = dns_name;
        type = "TXT";
        rrdatas = [
          "v=spf1 include:spf.messagingengine.com ?all"
          "google-site-verification=bOCcwr5Tv4_OTbSd_I4qPw_G5eoslPyAZ9c0NzqJ7n4"
          "google-site-verification=MoMPhxfm9W0rOK06GVkZwXh8pGF8aFL_QSk4GcPMD6c"
        ];
      };
    };
  in
    pipe records [
      attrValues
      mergeAttrsList
      (mapAttrs (_: mergeAttrs common_args))
    ];
}
