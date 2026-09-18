# The base image is built from the pinned MatIEC-era OpenPLC commit by
# scripts/build_openplc_base.py. Never replace it with upstream latest: that
# toolchain no longer accepts MatIEC Config0.c/glueVars.c output.
FROM plc-agent-openplc:m2-base

ARG MATIEC_VERSION=v4.0.11
ARG MATIEC_SHA256=6f1d99dd0846a2243f130d70a1d0393cf884bb7a747022d6ef14ac9f5312bd0c
ARG XML2ST_VERSION=v4.0.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl file unzip zip \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    mkdir -p /tmp/matiec /usr/local/share/matiec; \
    curl -fsSL "https://github.com/Autonomy-Logic/matiec/releases/download/${MATIEC_VERSION}/matiec-linux-x64.tar.gz" -o /tmp/matiec.tar.gz; \
    echo "${MATIEC_SHA256}  /tmp/matiec.tar.gz" | sha256sum -c -; \
    tar xzf /tmp/matiec.tar.gz -C /tmp/matiec --strip-components=1; \
    install -m 0755 /tmp/matiec/iec2c /usr/local/bin/iec2c; \
    install -m 0755 /tmp/matiec/iec2iec /usr/local/bin/iec2iec; \
    cp -r /tmp/matiec/lib /usr/local/share/matiec/lib; \
    rm -rf /tmp/matiec /tmp/matiec.tar.gz

RUN set -eux; \
    mkdir -p /tmp/xml2st; \
    curl -fsSL "https://github.com/Autonomy-Logic/xml2st/releases/download/${XML2ST_VERSION}/xml2st-linux-x64.tar.gz" -o /tmp/xml2st.tar.gz; \
    tar xzf /tmp/xml2st.tar.gz -C /tmp/xml2st --strip-components=1; \
    install -m 0755 /tmp/xml2st/xml2st /usr/local/bin/xml2st; \
    rm -rf /tmp/xml2st /tmp/xml2st.tar.gz; \
    xml2st --help >/dev/null

RUN mkdir -p /workspace/scripts
COPY scripts/compile_st.sh /workspace/scripts/compile_st.sh
RUN chmod 0755 /workspace/scripts/compile_st.sh \
    && printf 'PROGRAM Main\nVAR\n    X : BOOL;\nEND_VAR\nX := NOT X;\nEND_PROGRAM\n' >/tmp/smoke.st \
    && mkdir /tmp/matiec-smoke \
    && cd /tmp/matiec-smoke \
    && iec2c -f -l -p -I /usr/local/share/matiec/lib /tmp/smoke.st \
    && rm -rf /tmp/matiec-smoke /tmp/smoke.st \
    && gcc --version >/dev/null

WORKDIR /workdir
CMD ["bash", "./start_openplc.sh"]
