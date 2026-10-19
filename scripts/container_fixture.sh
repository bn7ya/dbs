#!/bin/sh
set -eu

usage="usage: sudo $0 docker|podman DIRECTORY [ACCOUNT] [NAME]"
if [ "$(id -u)" -ne 0 ]; then
    echo "$usage" >&2
    exit 2
fi

engine=${1:-}
directory=${2:-}
account=${3:-dbs-ssh}
name=${4:-shop}
case "$engine" in
    docker|podman) ;;
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
project="$directory/$name"
image="localhost/dbs-live-$name"

runtime="/run/user/$(id -u "$account")"
install -d -m 700 -o "$account" "$runtime"

as_account() {
    su "$account" -s /bin/sh -c "unset XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME; export XDG_RUNTIME_DIR='$runtime'; cd '$project' && $1"
}

if [ -d "$project" ]; then
    as_account "$engine compose down --volumes" >/dev/null 2>&1 || true
    rm -rf "$project"
fi
cp -R "$repository/tests/containers/project" "$project"
sed "s|localhost/dbs-live-shop|$image|" "$repository/tests/containers/project/compose.yaml" > "$project/compose.yaml"
mv "$project/env.example" "$project/.env"
python3 -m pip wheel --quiet --no-deps --wheel-dir "$project/wheelhouse" "$repository"
python3 -m pip download --quiet --dest "$project/wheelhouse" --only-binary=:all: \
    --python-version 3.12 --implementation cp --abi cp312 --abi abi3 --abi none \
    --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
    --platform manylinux_2_27_x86_64 --platform manylinux_2_28_x86_64 \
    "$project"/wheelhouse/django_dbs-*.whl
chown -R "$account:" "$project"
install -d -o "$account" -g "$(id -g "$account")" -m 0700 "$project/backups"

if [ "$engine" = docker ]; then
    getent group docker >/dev/null || groupadd docker
    usermod -aG docker "$account"
    chgrp docker /var/run/docker.sock
    chmod 660 /var/run/docker.sock
else
    if ! grep -q "^$account:" /etc/subuid; then
        usermod --add-subuids 200000-265535 --add-subgids 200000-265535 "$account"
    fi
    home=$(getent passwd "$account" | cut -d: -f6)
    install -d -o "$account" "$home/.config" "$home/.config/containers"
    if [ ! -f "$home/.config/containers/containers.conf" ]; then
        printf '[engine]\ncompose_providers = ["podman-compose"]\ncompose_warning_logs = false\n' \
            > "$home/.config/containers/containers.conf"
        chown "$account" "$home/.config/containers/containers.conf"
    fi
fi

if [ "$engine" = docker ]; then
    chown 10001:10001 "$project/backups"
else
    as_account "podman unshare chown 10001:10001 backups"
fi
as_account "$engine build --network none --tag $image ." >&2
as_account "$engine compose up -d" >&2
waited=0
until as_account "$engine compose exec -T web python manage.py migrate --check" >/dev/null 2>&1; do
    waited=$((waited + 1))
    if [ "$waited" -gt 120 ]; then
        as_account "$engine compose logs" >&2 || true
        echo "The application did not finish migrating." >&2
        exit 1
    fi
    sleep 1
done

echo "DBS_TEST_CONTAINER_ENGINE=$engine"
echo "DBS_TEST_CONTAINER_FOLDER=$project"
