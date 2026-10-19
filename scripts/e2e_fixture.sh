#!/bin/sh
set -eu

usage="usage: sudo $0 DIRECTORY [docker|podman] [ACCOUNT]"
if [ "$(id -u)" -ne 0 ]; then
    echo "$usage" >&2
    exit 2
fi

directory=${1:-}
engine=${2:-}
account=${3:-dbs-ssh}
case "$engine" in
    ""|docker|podman) ;;
    *) echo "$usage" >&2; exit 2 ;;
esac
if [ -z "$directory" ]; then
    echo "$usage" >&2
    exit 2
fi
if ! id "$account" >/dev/null 2>&1; then
    echo "$account does not exist; start scripts/openssh_test_server.sh first." >&2
    exit 2
fi

repository=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$directory"
directory=$(cd "$directory" && pwd)
chown root: "$directory"
chmod 755 "$directory"
group=$(id -g "$account")
host=${DBS_TEST_SSH_HOST:-127.0.0.1}
port=${DBS_TEST_SSH_PORT:-2222}
password=${DBS_TEST_SSH_PASSWORD:-dbs-ssh-password}
app="$directory/app"
target="$directory/target"
existing="$directory/existing"
wheels="$directory/wheelhouse"
container_name=e2e-shop

as_account() {
    su "$account" -s /bin/sh -c "cd '$1' && $2"
}

rm -rf "$wheels"
python3 -m pip wheel --quiet --no-deps --wheel-dir "$wheels" "$repository"

project() {
    folder=$1
    secret=$2
    rm -rf "$folder"
    install -d -m 755 "$folder"
    cp -R "$repository/tests/containers/project/manage.py" \
        "$repository/tests/containers/project/shop" \
        "$repository/tests/containers/project/notes" "$folder"
    install -d -m 755 "$folder/data" "$folder/media" "$folder/media/uploads"
    install -d -m 700 "$folder/backups"
    printf 'hello from the e2e fixture\n' > "$folder/media/uploads/a.txt"
    head -c 2048 /dev/urandom > "$folder/media/uploads/b.bin"
    {
        echo "SHOP_SECRET_KEY=$secret"
        echo "SHOP_DATABASE=$folder/data/db.sqlite3"
        echo "SHOP_BACKUP_DIR=$folder/backups"
    } > "$folder/.env"
    chmod 600 "$folder/.env"
}

project "$app" e2e-app-secret
python3 -m venv "$app/.venv"
"$app/.venv/bin/pip" install --quiet --disable-pip-version-check "$wheels"/django_dbs-*.whl
project "$target" e2e-target-secret
cp -RP "$app/.venv" "$target/.venv"

rm -rf "$existing"
install -d -m 755 "$existing"
for day in 2026-09-30 2026-09-29; do
    printf 'select %s;\n' "$day" | gzip -c > "$existing/db-$day.sql.gz"
done

chown -R "$account:$group" "$app" "$target" "$existing"
chmod -R go-w "$app" "$target" "$existing"
as_account "$app" ".venv/bin/python manage.py migrate --noinput" >&2
as_account "$target" ".venv/bin/python manage.py migrate --noinput" >&2

if [ -n "$engine" ]; then
    "$repository/scripts/container_fixture.sh" "$engine" "$directory" "$account" "$container_name" >/dev/null
fi

fingerprint=$(ssh-keyscan -p "$port" -t ed25519 "$host" 2>/dev/null | ssh-keygen -lf - | cut -d' ' -f2)
if [ -z "$fingerprint" ]; then
    echo "No SSH server answers on $host:$port; start scripts/openssh_test_server.sh first." >&2
    exit 1
fi

echo "E2E_SSH_HOST=$host"
echo "E2E_SSH_PORT=$port"
echo "E2E_SSH_USER=$account"
echo "E2E_SSH_PASSWORD=$password"
echo "E2E_SSH_FINGERPRINT=$fingerprint"
echo "E2E_SSH_PROJECT_DIR=$app"
echo "E2E_SSH_PYTHON=$app/.venv/bin/python"
echo "E2E_SSH_REMOTE_BACKUP_DIR=$app/backups"
echo "E2E_SSH_ENV_PATH=$app/.env"
echo "E2E_SSH_MEDIA_DIR=$app/media"
echo "E2E_SSH_EXISTING_DIR=$existing"
echo "E2E_SSH_EXISTING_FILES=db-2026-09-30.sql.gz,db-2026-09-29.sql.gz"
echo "E2E_SSH_TARGET_PROJECT_DIR=$target"
echo "E2E_SSH_TARGET_PYTHON=$target/.venv/bin/python"
echo "E2E_SSH_TARGET_REMOTE_BACKUP_DIR=$target/backups"
echo "E2E_SSH_FS=/"
if [ -n "$engine" ]; then
    echo "E2E_CONTAINER_ENGINE=$engine"
    echo "E2E_CONTAINER_FOLDER=$directory/$container_name"
fi
