#! /bin/bash

# ensure required extensions are installed

function install_apt_packages() {
    # Check if running as root
    if [ "$(id -u)" -ne 0 ]; then
        echo "This script must be run as root, you are running as $(whoami) (uid: $(id -u))"
        exit 1
    fi
    # Check if package exists before installing
    if ! dpkg -l "$1" &> /dev/null; then
        echo "Installing package $1..."
        apt-get install -y "$1"
    fi
}



if [ -n "$TARGET_PACKAGES" ]; then
    apt update
    for pkg in $(echo $TARGET_PACKAGES | tr "," "\n"); do
        install_apt_packages $pkg
    done
fi

echo "Now calling docker-entrypoint.sh with args: $@"
exec docker-entrypoint.sh postgres "$@"