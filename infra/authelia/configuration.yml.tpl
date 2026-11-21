# Templat konfigurasi Authelia.
#
# Jangan diedit langsung. Jalankan `task sso-config` untuk menghasilkan
# infra/authelia/configuration.yml dari BASE_DOMAIN, SCHEME, dan
# AUTHELIA_SESSION_SECRET di .env.
---
theme: 'dark'
server:
  address: 'tcp://:9091'
  endpoints:
    authz:
      forward-auth:
        implementation: 'ForwardAuth'

log:
  level: 'info'

totp:
  disable: true

identity_validation:
  reset_password:
    jwt_secret: '__SESSION_SECRET__'

storage:
  local:
    path: '/data/db.sqlite3'
  encryption_key: '__SESSION_SECRET__'

notifier:
  filesystem:
    filename: '/data/notifications.txt'

authentication_backend:
  file:
    path: '/config/users.yml'

access_control:
  default_policy: 'deny'
  rules:
    # Authelia sendiri tidak boleh butuh login.
    - domain: 'auth.__BASE_DOMAIN__'
      policy: 'bypass'

    # Halaman admin portal hanya untuk grup admin.
    - domain: 'app.__BASE_DOMAIN__'
      resources:
        - '^/admin(.*)$'
      subject: 'group:admin'
      policy: 'one_factor'
    - domain: 'app.__BASE_DOMAIN__'
      resources:
        - '^/admin(.*)$'
      policy: 'deny'

    # Portal dan Grafana cukup satu faktor untuk semua peran yang login.
    - domain: 'app.__BASE_DOMAIN__'
      policy: 'one_factor'
    - domain: 'grafana.__BASE_DOMAIN__'
      policy: 'one_factor'
    - domain: 'metabase.__BASE_DOMAIN__'
      policy: 'one_factor'

    # Prefect hanya untuk admin, karena bisa menjalankan dan menghapus job.
    - domain: 'prefect.__BASE_DOMAIN__'
      subject: 'group:admin'
      policy: 'one_factor'

session:
  name: 'karhutla_session'
  secret: '__SESSION_SECRET__'
  expiration: '8h'
  cookies:
    - domain: '__BASE_DOMAIN__'
      authelia_url: '__SCHEME__://auth.__BASE_DOMAIN__'
      default_redirection_url: '__SCHEME__://app.__BASE_DOMAIN__'
      same_site: 'lax'
