{
  config,
  nix,
  ...
}:
with nix; {
  data.google_iam_policy.bucket.binding = let
    roles."roles/storage.admin" = ["projectOwner:${config.provider.google.project}"];
    roles."roles/storage.objectViewer" = ["allUsers"];
    roles."roles/storage.objectAdmin" = ["\${ google_service_account.vilfer.member }"];
  in
    mapAttrsToList (role: members: {inherit role members;}) roles;
  resource = {
    google_storage_bucket.main = {
      depends_on = ["google_project_service.storage"];
      name = "vilf-org";
      location = "US";
      uniform_bucket_level_access = true;
      website.main_page_suffix = "index.html";
      website.not_found_page = "error.html";
    };
    google_storage_bucket_iam_policy.main = {
      bucket = "\${ google_storage_bucket.main.name }";
      policy_data = "\${ data.google_iam_policy.bucket.policy_data }";
    };
    google_compute_backend_bucket.main = rec {
      depends_on = ["google_project_service.compute"];
      name = bucket_name;
      bucket_name = "\${ google_storage_bucket.main.name }";
      enable_cdn = true;
      compression_mode = "DISABLED";
      custom_response_headers = ["Strict-Transport-Security:max-age=31536000; includeSubDomains; preload"];
    };
  };
}
