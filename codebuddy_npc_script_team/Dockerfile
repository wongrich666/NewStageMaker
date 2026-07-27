FROM cnbcool/default-npc:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-requests ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/run_script_team.py scripts/validate_script_team.py /opt/script-team/
COPY .codebuddy/skills /root/.codebuddy/skills
