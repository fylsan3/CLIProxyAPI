ARG BASE
FROM ${BASE}
USER root
COPY test-ca.crt /usr/local/share/ca-certificates/cpa-local-test.crt
RUN update-ca-certificates
