FROM ghcr.io/zeroclaw-labs/zeroclaw:debian

# uv — manages Python venv for camera skill (inline script dependencies)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Camera skill
# zeroclaw loads skills from workspace_dir/skills/<name>/ (see src/skills/mod.rs)
# Shell commands run with CWD = workspace_dir (see src/tools/skill_tool.rs)
# so SKILL.toml command "uv run skills/camera-control/scripts/camera.py ..."
# resolves correctly from /zeroclaw-data/workspace
COPY --chown=65534:65534 ../camera-control /zeroclaw-data/workspace/skills/camera-control

# SOUL.md — loaded by zeroclaw personality system from workspace root
# (see src/agent/personality.rs: PERSONALITY_FILES includes "SOUL.md")
COPY --chown=65534:65534 SOUL.md /zeroclaw-data/workspace/SOUL.md

# Entrypoint: writes camera_config.ini + zeroclaw config from env, then execs zeroclaw
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER 65534:65534
ENTRYPOINT ["/entrypoint.sh"]
CMD ["daemon"]
