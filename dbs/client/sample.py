SAMPLE_CONFIG = '''# DBS client configuration.
#
# Copy this to ./dbs-client.toml or ~/.config/dbs/client.toml and edit it.
# Anything set under [defaults] applies to every server unless the server
# overrides it. Keep this file at chmod 600 if it holds a literal secret.

[defaults]
server = "production"
dest = "~/dbs-backups"
keep = 14
keep_remote = 7
interval = "6h"

# A server reached with a .pem or OpenSSH private key.
[servers.production]
host = "app.example.com"
username = "deploy"
port = 22
key_filename = "~/.ssh/production.pem"
# The key's own passphrase, when the key file is encrypted:
# key_passphrase_env = "DBS_PRODUCTION_KEY_PASSPHRASE"
known_hosts = "~/.ssh/known_hosts"
connect_timeout = 30

# Where django-dbs lives on that server.
project_dir = "/srv/myproject"
python = "/srv/myproject/.venv/bin/python"
manage = "manage.py"
django_settings_module = "myproject.settings.production"
remote_dir = "/var/backups/myproject"

# The backup encryption passphrase. Prefer the environment over a literal.
passphrase_env = "DBS_PASSPHRASE"

prefix = "production"
dest = "~/dbs-backups/production"
keep = 30

# A server reached with a password instead of a key.
[servers.staging]
host = "10.0.0.7"
username = "ubuntu"
password_env = "DBS_STAGING_SSH_PASSWORD"
project_dir = "/srv/staging"
python = "/srv/staging/.venv/bin/python"
remote_dir = "/srv/staging/backups"
passphrase_env = "DBS_STAGING_PASSPHRASE"
prefix = "staging"
keep = 3

# Reach a server through ssh-agent by naming neither a key nor a password.
'''
