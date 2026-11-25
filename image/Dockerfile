ARG FIREWALL
ARG BASE
FROM ${FIREWALL} AS firewall
FROM ${BASE} AS trimmed
USER root
COPY --from=firewall /usr/sbin/xtables-nft-multi /usr/sbin/xtables-nft-multi
COPY --from=firewall /usr/lib/aarch64-linux-gnu/libxtables.so.* /usr/lib/aarch64-linux-gnu/
COPY --from=firewall /usr/lib/aarch64-linux-gnu/libmnl.so.* /usr/lib/aarch64-linux-gnu/
COPY --from=firewall /usr/lib/aarch64-linux-gnu/libnftnl.so.* /usr/lib/aarch64-linux-gnu/
COPY --from=firewall /usr/lib/aarch64-linux-gnu/xtables /usr/lib/aarch64-linux-gnu/xtables
RUN ln -s xtables-nft-multi /usr/sbin/iptables-nft && ln -s xtables-nft-multi /usr/sbin/ip6tables-nft && mkdir -p /network-config /mock && chown 1001:1001 /network-config /mock && chmod 700 /network-config /mock
COPY --chown=pwuser:pwuser account_identity.py /opt/native/account_identity.py
COPY --chown=pwuser:pwuser account_identity.py /opt/sample/account_identity.py
COPY --chown=pwuser:pwuser worker entry.py retention.py retention_cli.py network_gate.py network_boot.py socks_adapter.py idle_schedule.py locale_probe.py /opt/native/
COPY --chown=pwuser:pwuser profile_store.py /opt/sample/profile_store.py
COPY --chown=pwuser:pwuser browser_worker.py /opt/sample/worker.py
COPY --chown=pwuser:pwuser window_control.py /opt/sample/window_control.py
COPY --chown=pwuser:pwuser bundle_io.py /opt/native/bundle_io.py
COPY --chown=pwuser:pwuser sandbox_status.py /opt/sample/sandbox_status.py
COPY viewer.html /usr/share/novnc/desktop.html
RUN ln -snf /network-config/localtime /etc/localtime && ln -snf /network-config/timezone /etc/timezone
RUN rm -rf /ms-playwright/firefox-* /ms-playwright/webkit-* /ms-playwright/chromium_headless_shell-*
FROM scratch
COPY --from=trimmed / /
USER root
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PLAYWRIGHT_BROWSERS_PATH=/ms-playwright HOME=/tmp/chrome-home LANG=C.UTF-8 LC_ALL=C.UTF-8 LANGUAGE=en_US:en
ENTRYPOINT ["python3","-B","/opt/native/network_boot.py"]
