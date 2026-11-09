# Development notes

Development-side open questions and things to fix later: what the code does not do yet, a
question nobody can answer yet, an idea that fell short of a recommendation. Not a design
document and not a changelog.

**Adding an entry:** when `/finish` lists a non-critical extra the user wants kept, or a
round defers something, add a heading with the date and the branch/round it came from, the
item itself and its next step or where it is configured. **Resolving an entry:** the change
that resolves it deletes it — this file only ever shows what is still open. Before an entry
is deleted or renamed, anything that points at it by heading is updated in the same change. A feature's
`/feature` concept stage reads it for items the feature could take with it.

Entries dated before November 2026 come from the previous pipeline; "step 8" and the round
numbers point into the numbered plan files under `development/`, which stay as history.

## No DST feed for kommunal- and regionsvalg

2026-11-03, `feat/dkvalg-folketingsvalg-replay` round 1. DST's XML feeds (dst.dk/Valg/xml.htm) cover only Folketingsvalg, EP-valg and folkeafstemning. The original spec also listed kommunal- and regionsvalg. Next step: find another official source (e.g. valg.dk / the ministry) or drop them from the project's aims.

## CLI output encoding

2026-11-03, `feat/dkvalg-folketingsvalg-replay` round 1. `dkvalg replay` raises `UnicodeEncodeError` when stdout cannot encode Danish place names (an ASCII-only stream); pinned by a test as a documented limitation. Next step: reconfigure the stream with `errors="replace"` in `cli.main` if it ever bites a real terminal.

## Finding the current election's id

2026-11-04, `feat/dkvalg-live-polling` round 1. `poll` takes an election id or URL as given (DST ids look like `Valg2546527`). Finding the current election automatically means reading the list on dst.dk/valg/xml.htm, an HTML page whose layout may change. Next step: decide, once someone needs it, between scraping that page and keeping the id a manual setting.

## A recorder failure fails the fetch

2026-11-04, `feat/dkvalg-live-polling` round 1. `HttpSource.fetch` writes the capture before it commits its state, so a disk failure makes the fetch fail and `poll` keeps handing out the last good election with the error. The alternative is to keep fetching and rewrite every held body at the next successful record. Next step: decide once a real night shows how often the disk fails.

## How often DST answers 304 to both validators

2026-11-04, `feat/dkvalg-live-polling` round 1. `HttpSource` sends `If-None-Match` and `If-Modified-Since` together. A live probe of four consecutive polls of the still-served 2026 election gave 200, 304, 200 (the first being unconditional): DST's nodes disagree on ETags, so a poll often gets the full overview as a 200, which the byte comparison then treats as no change. Correctness holds; only politeness suffers. Next step: measure over a longer run and decide whether to drop `If-None-Match`.

## Two kinds of time in replay output

2026-11-04, `feat/dkvalg-live-polling` round 1. `replay` on a plain feed directory prints naive Danish local time (DST's `SenestRettet`), while capture replay and `poll` print timezone-aware UTC fetch times. Nothing compares across them, but a caller mapping `ReplayStep.at` and `CaptureStep.at` onto one timeline needs to know. Next step: decide, when the Home Assistant side consumes steps, whether to expose one convention.

## Broken pipe in the CLI

2026-11-04, `feat/dkvalg-live-polling` round 1. `python -m dkvalg replay <dir> | head` ends with a `BrokenPipeError` traceback (the same on the round 1 path, and `poll` inherits it). Next step: catch `BrokenPipeError` in `cli.main` and exit quietly if anyone pipes the output.

## EP seats are not in DST's feeds

2026-11-04, `feat/dkvalg-diff-and-ep` round 1. DST's Europa-Parlamentsvalg result feeds (checked on the 9 June 2024 election) carry votes and percentages only, no seat attributes at any level, so every EP seat field is `None` and `diff` never reports EP seat changes. Denmark's 15 seats are allocated nationally by d'Hondt among the lists. Next step: if seats are wanted, compute them from the national votes in a separate feature, or find an official source that publishes them.

## Election type is recognised by a name prefix

2026-11-04, `feat/dkvalg-diff-and-ep` round 1. `parse_any_overview` picks the adapter by `startswith` on `ValgNavn` (`Folketingsvalg`, `Europa-Parlamentsvalg`, `Folkeafstemning`), case-sensitive, so a bare prefix or `Folketingsvalgxyz` is accepted and a respelling by DST (for example `Europaparlamentsvalg`) is refused with the supported types listed. Next step: if DST ever changes the spelling, add the new prefix in the registry; there is no feed field that states the election type.

## diff on a finished election shows seats arriving with the count

2026-11-04, `feat/dkvalg-diff-and-ep` round 1. In live feeds DST computes seats after a place is first counted, so `--diff` prints a `seats ... - -> n` line when they arrive; replaying a finished election's end-state files reveals a place with its seats already present, so no seat line appears at that step (documented and pinned by tests). Next step: if end-state replays should also show seat lines, derive them from `PlaceCounted` places that carry seats, or wait for a recorded live capture, which shows the real order.

## Referendum answers are carried as party results

2026-11-06, `feat/dkvalg-folkeafstemning` round 1. DST encodes a referendum's answers (JA, NEJ) as `Parti` entries, so the model reuses `PartyResult` and `Place.parties` for them and the docs say so; the names `PartyResult` and `is_party` read oddly for a referendum. Next step: if a non-party kind of result needs a clearer name, rename `PartyResult` and `Place.parties` to a neutral term in a deliberate, breaking round; not worth doing for one more election type.
