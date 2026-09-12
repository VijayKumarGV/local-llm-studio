# Minimal Python image used ONLY for the sandboxed execute_python_code tool.
# Every container:
#   - runs as unprivileged user
#   - --network=none (enforced at `docker run` time)
#   - --read-only rootfs (enforced at `docker run` time)
#   - --tmpfs /tmp for scratch writes
#   - --memory=256m + --cpus=1 + --pids-limit=64 (enforced at `docker run` time)
#   - --cap-drop=ALL + --security-opt=no-new-privileges
#
# Build once:   docker build -f docker/sandbox.Dockerfile -t studio-sandbox:latest docker/
FROM python:3.12-slim

RUN adduser --disabled-password --gecos '' --uid 1500 sandbox
USER sandbox
WORKDIR /work

# Fail fast if anyone tries to `docker run` without a command.
CMD ["python", "-c", "raise SystemExit('no code provided to sandbox')"]
