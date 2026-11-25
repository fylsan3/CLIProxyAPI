ARG BASE
FROM ${BASE}
USER 1001:1001
COPY --chown=pwuser:pwuser entry.py origin.py socks.py accounts.json /fixture/
ENTRYPOINT ["python3","-B","/fixture/entry.py"]
