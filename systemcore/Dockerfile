FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential bc bison flex libssl-dev libelf-dev libncurses-dev \
    rsync cpio kmod autoconf automake libtool pkg-config git curl ca-certificates \
    xz-utils file \
    && rm -rf /var/lib/apt/lists/*
