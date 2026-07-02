# Engine7B Platform Postgres: pgvector + Apache AGE + pg_cron (PG16)
FROM pgvector/pgvector:pg16

USER root

ARG AGE_VERSION=release/PG16/1.5.0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        build-essential \
        postgresql-server-dev-16 \
        libreadline-dev \
        zlib1g-dev \
        flex \
        bison \
        postgresql-16-cron; \
    git clone --branch "${AGE_VERSION}" --depth 1 https://github.com/apache/age.git /tmp/age; \
    make -C /tmp/age; \
    make -C /tmp/age install; \
    rm -rf /tmp/age; \
    apt-get purge -y git build-essential flex bison; \
    apt-get autoremove -y; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

USER postgres
