# Folkeafstemning 3 December 2015 fixtures

Unmodified copies of the XML feeds DST (Danmarks Statistik) published for the
Folkeafstemning held on 3 December 2015: the referendum on converting the Danish opt-out on justice and home affairs (NEJ won). They are test data for `dkvalg`: nothing here
was edited, reformatted or re-encoded, and every file keeps its UTF-8 byte order mark.

- Retrieved: 2026-11-06
- Source directory: https://www.dst.dk/valg/Valg1664255/xml/
- Overview feeds: `generel.xml` (https://www.dst.dk/valg/Valg1664255/xml/generel.xml) and
  `valgdag.xml` (https://www.dst.dk/valg/Valg1664255/xml/valgdag.xml); the election name is
  `Folkeafstemning torsdag 3. december 2015` (a single space here, unlike 2022 and 2009)
- Result feeds: the 107 files `valgdag.xml` lists in its `filnavn` attributes, each at
  `https://www.dst.dk/valg/Valg1664255/xml/<file name>` (`valgdag_0.xml` is "Hele landet", `valgdag_999.xml` the preliminary
  "optalling" tally, then 3 landsdele, 10 storkredse and 92 opstillingskredse). `fintal.xml` is not
  part of the set.
- Referendum answers are served as `Parti` entries: id 434284 letter `JA` and id 434285
  letter `NEJ` (listed as "opstillede partier" in `generel.xml`), with votes and percent
  like any party. There are no seat attributes (no `Mandater`, `Kredsmandater` or
  `Tillaegsmandater`) and no "Uden for partier" entry, so every seat field of the model
  is `None`.
- Same structure as the Folketingsvalg feeds in `../folketingsvalg_2026` and the
  Europa-Parlamentsvalg feeds in `../ep_2024`.
- Feed documentation: `docs/XmlFeeds20260305.pdf` at the repo root.

`SHA256SUMS` records the SHA-256 of each of the 109 XML files at download time
(`sha256sum -c SHA256SUMS` checks them). `.gitattributes` marks this directory `-text`
so a checkout never rewrites line endings.
