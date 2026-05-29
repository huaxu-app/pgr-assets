# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
LABEL authors="nova"

# git is needed for the pycricodecs git+https dependency
RUN apt-get -qq update && \
    apt-get -yqq --no-install-recommends install \
      build-essential git && \
    rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached unless lockfile changes), then the project.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.13-slim-bookworm AS publish

# Static ffmpeg (pinned) instead of Debian's package + its ~900 codec shared
# libs. ffprobe is not used by this project, so only ffmpeg is copied. Each
# static binary is ~135MB. Bump the tag to update ffmpeg.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/

# Editable install: the venv's .pth points at /app/src, so both are required.
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
# Pass the subcommand and its flags as args, e.g.:
#   docker run -v ./out:/out pgr-assets extract --preset global --all-images --output /out
ENTRYPOINT ["pgr-assets"]
