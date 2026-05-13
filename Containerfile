FROM registry.redhat.io/ubi9/ubi-minimal:latest AS base

RUN microdnf install -y \
        python3.12 \
        python3.12-pip \
        python3.12-devel \
        libpq-devel \
        gcc \
        shadow-utils \
    && microdnf clean all

RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python3 && \
    ln -sf /usr/bin/python3.12 /usr/local/bin/python && \
    ln -sf /usr/bin/pip3.12 /usr/local/bin/pip3 && \
    ln -sf /usr/bin/pip3.12 /usr/local/bin/pip

RUN useradd -r -m -d /app bridge
WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY config/ config/

RUN pip3.12 install --no-cache-dir . && \
    pip3.12 install --no-cache-dir psycopg2-binary

USER bridge

ENTRYPOINT ["aap-bridge"]


FROM base AS api

USER root

RUN pip3.12 install --no-cache-dir '.[api]'

RUN mkdir -p exports reports logs && \
    chown -R bridge:bridge exports reports logs

USER bridge

EXPOSE 8000

ENTRYPOINT ["aap-bridge", "serve", "--host", "0.0.0.0", "--port", "8000"]
