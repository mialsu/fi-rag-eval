# ADR-0002 — Authority, not municipality, is the jurisdiction key

- **Date:** 2026-08-26
- **Status:** accepted

## Context

`DESIGN.md:67` makes "municipality as a hard filter, not a soft signal" a key decision, on the
premise stated in `README.md:18-19` that "Finnish municipalities each publish their own waste
regulations". Checked against the sources during shaping, **that premise is false.**

- Waste regulations are approved by the *kunnallinen jätehuoltoviranomainen*, which in most of
  Finland is a joint regional board (*jätelautakunta*) acting for many municipalities at once.
- Turku is **1 of 18** municipalities under Lounais-Suomen jätehuoltolautakunta (Aura, Kaarina,
  Kemiönsaari, Lieto, Marttila, Masku, Mynämäki, Naantali, Nousiainen, Paimio, Parainen, Pöytyä,
  Raisio, Rusko, Salo, Sauvo, Turku, Uusikaupunki), ~450,000 residents.
- The text is uniform across the whole area: *"Määräykset ovat yhtenäiset kaikissa jätelautakunnan
  toimialueen kunnissa."*

So there is no document called "Turku's jätehuoltomääräykset", and two municipalities under one
board have identical rules. A municipality-keyed filter models a unit that does not publish.

## Decision

The **Authority** is a first-class entity and the hard filter's key. A document belongs to exactly
one authority. A checked-in *kunta* → authority map resolves the resident's municipality; the
municipality is user-facing input and **never appears on a chunk**.

The authority carries identity, `effective_from` and supersession, because regulations are
re-issued: Southwest Finland's came into force 1.7.2023, were amended 1.8.2024, and amended again
22.10.2025.

## Rejected alternatives

- **A denormalised `municipalities text[]` on each chunk**, filtered by containment — rejected
  because it works for filtering but erases the authority as an entity, leaving effective dates and
  supersession nowhere to live, and turning a boundary change into an UPDATE across every chunk of
  a document instead of one row in a map.
- **One metadata row per (document, municipality)** — rejected because it multiplies chunk metadata
  18× for Southwest Finland alone, and the duplication is the drifting kind: the same clause can end
  up with different metadata for Turku than for Raisio, which is precisely the cross-jurisdiction
  bug class the hard filter exists to make impossible.
- **Keeping the municipality as the key and treating the discrepancy as cosmetic** — rejected
  because golden-set labels are hand-written against this model. Getting it wrong means relabelling
  by hand, and hand-labelling is this project's scarcest resource.

## Consequences

**Easy.** Cross-authority contamination becomes equality on one id. Golden-set labels get a
well-defined answer to "which document should have answered this".

**Hard.** `DESIGN.md:83` wants "questions whose answer differs between municipalities" as a
golden-set category. Under this model that category is *empty* within an authority — real divergence
exists only across authority boundaries or through sub-municipal zone exceptions. The MVP corpus
therefore needs two authorities to test the filter at all.

**Living with.** The user says "Turku" and means an 18-municipality document. Every surface must
resolve that without implying Turku has its own rules.

---

## Amendment, 2026-08-27 (slice 4) — a municipality does NOT always resolve to exactly one authority

This ADR's model says a Municipality resolves to **exactly one** Authority, and
`manifest.resolve_municipality` enforces it: two authorities claiming one kunta is a hard error,
because silently picking one is the cross-jurisdiction answer the filter exists to prevent.

Ingesting Pirkanmaa produced a **counterexample read straight from the document**. Its
`1 § SOVELTAMISALA` lists the area as:

> Hämeenkyrön, Ikaalisten, Juupajoen, Kangasalan, Lempäälän, Mänttä-Vilppulan, Nokian, Oriveden,
> Parkanon, Pirkkalan, Pälkäneen, Ruoveden, **Sastamalan (Mouhijärven ja Suodenniemen osalta)**,
> Tampereen, Vesilahden, Virtain ja Ylöjärven muodostamalla alueella.

Sastamala is claimed **only for its former Mouhijärvi and Suodenniemi areas** — two municipalities
merged into Sastamala in 2009, whose waste authority did not follow the merger. The rest of
Sastamala is bound by a different authority's rules. The map is therefore **not a function** for
Sastamala, and no amount of care in the manifest makes it one.

**What slice 4 did about it (D4):** Sastamala is omitted from `municipalities` and recorded in a
new `partial_municipalities` field, so `resolve_municipality("Sastamala")` raises with a message
naming the partial coverage rather than the generic "no authority covers this municipality". The
16 whole kunnat resolve normally. No golden question uses Sastamala.

**What that costs:** a resident of Mouhijärvi or Suodenniemi is refused an answer the regulations
do in fact give them. That is the same trade this project already makes for taajama boundaries —
an honest refusal beats a confident wrong answer — and it is the right trade at this scale, because
listing Sastamala would make the harness confidently wrong for *most* of the kunta's residents,
which is product failure mode #1 wearing a correct-looking citation.

**What is still unresolved, and is the Owner's call, not this ADR's:** whether the design
eventually needs a level between Authority and Municipality. Finnish municipal mergers leave
former municipalities under different waste authorities, so this will recur as the corpus grows;
it is not a Pirkanmaa quirk. Modelling it needs a fourth level nothing else in the design has, and
it is deliberately out of slice 4's scope. Recorded in `REVIEW-DEBT.md` and in the slice-4 spec's
open questions.
