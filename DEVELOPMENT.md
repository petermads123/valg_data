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
