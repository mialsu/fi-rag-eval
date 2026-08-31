# ADR-0014 — the corpus is fetched at build time and baked into the image

- **Date:** 2026-08-31
- **Status:** accepted
- **Relates to:** ADR-0005 (why the image is Debian and not Alpine), ADR-0013 (the gate the image serves).

## Context

MVP tracer 4 puts the whole demo in containers, and the corpus is the awkward part. Four facts,
each verified rather than assumed:

1. **The PDFs are gitignored.** `data/raw/` is in `.gitignore` (4.7 MB, two documents), so a clean
   clone has none. Anything that copies them from the host makes the build depend on files a clean
   clone does not have — and "clone it and run `make eval`" is this project's own reproducibility
   claim.
2. **`ingest` cannot be used for half its job.** It fetches *and* writes to Postgres, and at build
   time there is no Postgres. There was no fetch-only path; tracer 4 added `fetch_sources` and
   `fi-rag-eval ingest --fetch-only` for exactly this.
3. **The corpus database is on tmpfs**, so a load is required on every container start regardless of
   where the PDFs live. The only question is whether that load also has to *download*.
4. **A container on this machine cannot reach one of the sources at all.** Measured:
   `curl` from a container to `lsjatehuoltolautakunta.fi` gives `connect 0.000s` and times out at
   **90 s**, while the host connects in **0.25 s**. DNS resolves from the container (to a different
   IP than the host gets) and the MTU is 1500 on both sides, so it is the bridge's egress. This is a
   property of this machine, not of the design — but it is what a run-time fetch would depend on.

Fact 4 is the one that decided it, and it decided it in the direction the Owner had already chosen
on 31 Aug 2026 before that measurement existed.

## Decision

**`docker build` fetches both documents and verifies each against the `sha256` the manifest pins,
and they are baked into the image.** A mismatch fails the build, which is the same rule
`ingest.fetch` already applies on the host: silently accepting a different document changes what
every golden label means.

`docker compose up` therefore needs **no network for the corpus** and does not depend on two
municipal web servers staying up. The container start chunks, indexes and writes the lemma columns
— about ten seconds — and nothing more.

**`make docker-build` passes `--network=host`**, because the build fetches and fact 4 says a bridged
container cannot. Reproducibility is unaffected: every byte downloaded is checked against the hash
in the manifest, so a build that succeeds has the same two documents whichever route it took. The
flag is in the Makefile with the measurement written beside it, so nobody removes it as noise or
copies it as a habit.

**The image also carries `eval/`**, not just `eval/frozen/`. An image that cannot run its own
regression gate is an image whose numbers nobody can reproduce, and `eval` gates against
`eval/baseline.json`. `eval/runs/` stays out via `.dockerignore` — it is gitignored, dirty-tree
output.

## Rejected alternatives

- **Fetch at run time, on every `docker compose up`** — rejected by the Owner, and then independently
  ruled out by fact 4. It keeps the image smaller and the corpus can never be stale relative to the
  manifest, but every boot would need network and depend on two municipal servers; `ingest.fetch`
  treats a checksum mismatch as a hard error deliberately, so a re-published document stops the
  container rather than degrading it. On this machine it would simply never start.
- **Copy `data/raw/` from the build context** — rejected. It is gitignored, so the build would work
  in this checkout and fail in a clean clone: the exact "it worked in the dev checkout" failure the
  clean-clone build gate exists to catch.
- **Baked *and* mounted through a named volume** — rejected. It sounds like flexibility and is two
  sources of truth for the corpus, where a volume's state silently decides which PDF was used. That
  is "two implementations of one behaviour" aimed at the one thing every published number describes.
- **Commit the PDFs to git** — rejected. 4.7 MB of third-party documents in the repository, versioned
  by us rather than by their publishers, and a second place for the manifest's `sha256` to disagree
  with. The manifest is the record; the bytes are fetched.
- **Fixing the bridge's egress instead of passing `--network=host`** — not rejected so much as out of
  scope. It needs daemon configuration and root on this machine, it would not travel with the
  repository, and the flag is honest about what the build does.
- **Alpine, to make the image smaller** — settled already by ADR-0005: neither libvoikko nor a
  Finnish hunspell dictionary is packaged for it, and the published cell is lemmatising. Verified for
  this image on Debian 13 trixie: `libvoikko1` 4.3.2, `voikko-fi` 2.5, `poppler-utils` 25.03. The
  image is 426 MB and that is the price of the analyser the numbers were computed with.

## Consequences

**Easy.** `docker compose up` works offline. The container's analyser fingerprint is
`9117b2f347e4c331`, identical to the host's and to `eval/baseline.json` — so the image's `eval`
reproduces the published table exactly (`lemma-reasm/0` recall@5 **0.820** at leakage **0.550**,
control `snowball/0` **0.680** at **0.332**, gate green, exit 0), which is the strongest form AD24
could take.

**Hard, and we live with it.** A manifest change now needs an image rebuild, and a stale image is a
stale corpus that still looks fine — the fingerprint and the baseline gate catch an analyser change
but *not* an out-of-date PDF, because the image's copy matches the hash the image's manifest pins.
The honest guard is that both travel in the same image: the manifest and the PDFs cannot disagree
inside one build. Across builds, `git` is the record.

**What this does not do.** It does not make the build hermetic — it still reaches the network, just
at build time rather than boot time. And `--network=host` means the build uses the host's resolver
and routes, so a build on a machine that cannot reach the sources still fails; it fails at
`docker build` with a clear error rather than at 3 a.m. on a container restart.
