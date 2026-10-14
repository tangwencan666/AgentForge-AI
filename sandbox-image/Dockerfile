FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox && mkdir -p /opt/agentforge /workspace && chown 10001:10001 /workspace
COPY launcher.py /opt/agentforge/launcher.py
RUN chmod 0555 /opt/agentforge/launcher.py
RUN touch /opt/agentforge/rootfs-canary && chmod 0666 /opt/agentforge/rootfs-canary
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT []
CMD ["python", "-I", "-S", "/opt/agentforge/launcher.py"]
