# Development notes

Development-side open questions and things to fix later: what the code does not do yet, a
question nobody can answer yet, an idea that fell short of a recommendation. Not a design
document and not a changelog.

**Adding an entry:** a heading, the date and the branch/round it came from, the item itself,
and its next step or where it is configured. **Resolving an entry:** the change that
resolves it deletes it — this file only ever shows what is still open. Step 8 of every round
ends by cleaning it: entries the branch resolved are removed, duplicates are merged, and
only open items are left. Before an entry is deleted or renamed, anything that points at it
by heading is updated in the same change.

## No DST feed for kommunal- and regionsvalg

2026-11-03, `feat/dkvalg-folketingsvalg-replay` round 1. DST's XML feeds (dst.dk/Valg/xml.htm) cover only Folketingsvalg, EP-valg and folkeafstemning. The original spec also listed kommunal- and regionsvalg. Next step: find another official source (e.g. valg.dk / the ministry) or drop them from the project's aims.

## Faithful replay needs recorded live captures

2026-11-03, `feat/dkvalg-folketingsvalg-replay` round 1. DST keeps only the latest state, and `SenestRettet` is a file's last change, so replay from saved end-state files cannot show intermediate landsdel/storkreds/national aggregates or seats. Next step: a recorder that saves every polled feed with its fetch time during a live election, built together with HttpSource (planned round 2); replay can then play those captures.

## Harden XML parsing before live polling

2026-11-03, `feat/dkvalg-folketingsvalg-replay` round 1. The adapter uses `xml.etree.ElementTree`, which is fine for saved DST files but expands entities from whatever it is given. Before HttpSource feeds it network responses (planned round 2), decide whether to add `defusedxml` (a dependency) or reject any DOCTYPE/entity declaration in the adapter.

## CLI output encoding

2026-11-03, `feat/dkvalg-folketingsvalg-replay` round 1. `dkvalg replay` raises `UnicodeEncodeError` when stdout cannot encode Danish place names (an ASCII-only stream); pinned by a test as a documented limitation. Next step: reconfigure the stream with `errors="replace"` in `cli.main` if it ever bites a real terminal.

## Finding the current election's id

2026-11-04, `feat/dkvalg-live-polling` round 1. `poll` takes an election id or URL as given (DST ids look like `Valg2546527`). Finding the current election automatically means reading the list on dst.dk/valg/xml.htm, an HTML page whose layout may change. Next step: decide, once someone needs it, between scraping that page and keeping the id a manual setting.
