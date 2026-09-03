# Spec-0085/T3
FROM auto-designer-vigil:latest

COPY . /opt/openagents-v02
RUN python3 -m pip install --no-deps /opt/openagents-v02

WORKDIR /workspace
ENTRYPOINT ["sleep", "infinity"]
