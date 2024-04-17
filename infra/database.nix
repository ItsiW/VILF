{nix, ...}:
with nix; {
  google.services = ["sqladmin"];
  resource = {
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
      name = "appsmith";
      instance = "\${ google_sql_database_instance.main.name }";
    };
    random_password.appsmith.length = 21;
    google_sql_user.appsmith = {
      name = "appsmith";
      instance = "\${ google_sql_database_instance.main.name }";
      password = "\${ random_password.appsmith.result }";
    };
  };
}
