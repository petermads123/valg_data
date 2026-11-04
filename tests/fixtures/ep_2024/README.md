# Europa-Parlamentsvalg 9 June 2024 fixtures

Unmodified copies of the XML feeds DST (Danmarks Statistik) published for the
Europa-Parlamentsvalg held on 9 June 2024. They are test data for `dkvalg`: nothing here
was edited, reformatted or re-encoded, and every file keeps its UTF-8 byte order mark.

- Retrieved: 2026-11-04
- Source directory: https://www.dst.dk/valg/Valg2546524/xml/
- Overview feeds: `generel.xml` (https://www.dst.dk/valg/Valg2546524/xml/generel.xml) and
  `valgdag.xml` (https://www.dst.dk/valg/Valg2546524/xml/valgdag.xml); the election name is
  `Europa-Parlamentsvalg søndag  9. juni 2024` (note the double space)
- Result feeds: the 107 files `valgdag.xml` lists in its `filnavn` attributes, each at
  `https://www.dst.dk/valg/Valg2546524/xml/<file name>` (`valgdag_0.xml` is "Hele landet",
  `valgdag_999.xml` the preliminary "optalling" tally, then 3 landsdele, 10 storkredse and
  92 opstillingskredse). `fintal.xml` is not part of the set.
- Same structure as the Folketingsvalg feeds in `../folketingsvalg_2026`, with one
  difference: the EP feeds carry no seat attributes (no `Mandater`, `Kredsmandater` or
  `Tillaegsmandater`), so every seat field of the model is `None`.
- Feed documentation: `docs/XmlFeeds20260305.pdf` at the repo root.

`SHA256SUMS` records the SHA-256 of each of the 109 XML files at download time
(`sha256sum -c SHA256SUMS` checks them). `.gitattributes` marks this directory `-text`
so a checkout never rewrites line endings.
