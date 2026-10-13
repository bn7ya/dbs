#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "usage: sudo $0 DIRECTORY [PORT]" >&2
    exit 2
fi

directory=${1:?usage: sudo $0 DIRECTORY [PORT]}
port=${2:-2222}
account=dbs-ssh
password=dbs-ssh-password
owner=${SUDO_USER:-root}

mkdir -p "$directory"
directory=$(cd "$directory" && pwd)

id "$account" >/dev/null 2>&1 || useradd --create-home --shell /bin/sh "$account"
echo "$account:$password" | chpasswd
home=$(getent passwd "$account" | cut -d: -f6)

rm -f "$directory/client_key" "$directory/client_key.pub" "$directory/host_key" "$directory/host_key.pub"
ssh-keygen -q -t ed25519 -N "" -C dbs-test-client -f "$directory/client_key"
ssh-keygen -q -t ed25519 -N "" -C dbs-host -f "$directory/host_key"
install -d -m 700 -o "$account" "$home/.ssh"
install -m 600 -o "$account" "$directory/client_key.pub" "$home/.ssh/authorized_keys"

cat > "$directory/sshd_config" <<EOF
Port $port
ListenAddress 127.0.0.1
HostKey $directory/host_key
PidFile $directory/sshd.pid
AuthorizedKeysFile .ssh/authorized_keys
PubkeyAuthentication yes
PasswordAuthentication yes
KbdInteractiveAuthentication no
UsePAM yes
AllowUsers $account
Subsystem sftp internal-sftp
EOF

mkdir -p /run/sshd
if [ -f "$directory/sshd.pid" ]; then
    kill "$(cat "$directory/sshd.pid")" 2>/dev/null || true
fi
/usr/sbin/sshd -f "$directory/sshd_config" -E "$directory/sshd.log"

printf '[127.0.0.1]:%s %s\n' "$port" "$(cut -d' ' -f1-2 "$directory/host_key.pub")" > "$directory/known_hosts"
chown "$owner" "$directory/client_key" "$directory/known_hosts"

echo "DBS_TEST_SSH_HOST=127.0.0.1"
echo "DBS_TEST_SSH_PORT=$port"
echo "DBS_TEST_SSH_USER=$account"
echo "DBS_TEST_SSH_PASSWORD=$password"
echo "DBS_TEST_SSH_KEY=$directory/client_key"
echo "DBS_TEST_SSH_KNOWN_HOSTS=$directory/known_hosts"
