# fi-rag-eval — one image, serving the gated demo (SPEC-mvp-demo tracer 4).
#
# Debian, not Alpine, and that is a settled question rather than a preference:
# ADR-0005 established that neither libvoikko nor a Finnish hunspell dictionary is
# packaged for Alpine, and the published cell (`lemma-reasm/0`) is lemmatising. An
# image without `voikko-fi` would fall through to a silently degraded analyser and
# serve a pipeline nobody measured. Verified on Debian 13 (trixie): libvoikko1
# 4.3.2, voikko-fi 2.5, poppler-utils 25.03.
#
# The corpus PDFs are fetched and verified HERE, at build time, and baked in
# (ADR-0014). They are gitignored, so a clean clone has none; fetching at build
# means `docker compose up` needs no network for the corpus and does not depend on
# two municipal web servers staying up. Each is checked against the sha256 the
# manifest pins, and a mismatch fails the build -- which is the same rule the host
# ingest follows, because silently accepting a different document changes what
# every golden label means.

# ---------------------------------------------------------------------------
# Stage 1 — the environment, resolved from the lockfile and nothing else
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

# uv by digest-pinned copy from its own image rather than `pip install uv`: the
# lockfile is only a reproducibility claim if the resolver that reads it is
# pinned too.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# The dependency layer is cached on the lockfile alone, so editing source does
# not re-resolve 73 packages. `--no-install-project` is what splits them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------------------------------------------------------------------------
# Stage 2 — the corpus, fetched and verified against the manifest
# ---------------------------------------------------------------------------
FROM builder AS corpus

COPY corpus/ ./corpus/
# Needs the venv (for the CLI) and the network. Touches no database: `ingest`
# without `--fetch-only` would need Postgres, which does not exist at build time.
RUN --mount=type=cache,target=/root/.cache/uv \
    .venv/bin/fi-rag-eval ingest --fetch-only --raw-dir /app/data/raw

# ---------------------------------------------------------------------------
# Stage 3 — the runtime
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

# libvoikko1 + voikko-fi: the analyser and its dictionary, both system packages
#   that `uv sync` cannot supply (ADR-0005).
# poppler-utils: `pdftotext`, which the extractor shells out to.
# ca-certificates: the gateway is reached over HTTPS via LiteLLM.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      libvoikko1 \
      voikko-fi \
      poppler-utils \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root. Nothing here writes to the image at runtime -- the corpus goes into
# Postgres, the demo's state into its own database -- so there is no reason for
# the process to be able to.
RUN useradd --create-home --uid 10001 demo
WORKDIR /app

COPY --from=builder --chown=demo:demo /app/.venv ./.venv
COPY --from=corpus  --chown=demo:demo /app/data/raw ./data/raw
COPY --chown=demo:demo src/ ./src/
COPY --chown=demo:demo corpus/ ./corpus/
# The whole of `eval/`, not just `frozen/`: `eval` gates against
# `eval/baseline.json`, and an image that cannot run its own regression gate is
# an image whose numbers nobody can reproduce. `eval/runs/` is excluded by
# .dockerignore -- it is gitignored, dirty-tree output.
COPY --chown=demo:demo eval/ ./eval/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER demo

# `serve` binds 0.0.0.0 because a container's loopback is reachable by nothing.
# That is not the same act as widening the bind on the host: compose publishes
# this on 127.0.0.1, and the token gate (ADR-0013) is what decides who may spend.
EXPOSE 8080
ENTRYPOINT ["fi-rag-eval"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
