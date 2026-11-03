# Folketingsvalg 24 March 2026 fixtures

Unmodified copies of the XML feeds DST (Danmarks Statistik) published for the
Folketingsvalg held on 24 March 2026. They are test data for `dkvalg`: nothing here
was edited, reformatted or re-encoded, and every file keeps its UTF-8 byte order mark.

- Retrieved: 2026-11-03
- Source directory: https://www.dst.dk/valg/Valg2546527/xml/
- Overview feeds: `generel.xml` (https://www.dst.dk/valg/Valg2546527/xml/generel.xml) and
  `valgdag.xml` (https://www.dst.dk/valg/Valg2546527/xml/valgdag.xml)
- Result feeds: the 107 files `valgdag.xml` lists in its `filnavn` attributes, each at
  `https://www.dst.dk/valg/Valg2546527/xml/<file name>` (`valgdag_0.xml` is "Hele landet",
  `valgdag_999.xml` the preliminary "optalling" tally, then 3 landsdele, 10 storkredse and
  92 opstillingskredse).
- Feed documentation: `docs/XmlFeeds20260305.pdf` at the repo root, from
  https://dst.dk/Valg/XmlFeeds20260305.pdf

`SHA256SUMS` records the SHA-256 of each of the 109 XML files at download time
(`sha256sum -c SHA256SUMS` checks them). `.gitattributes` marks this directory `-text`
so a checkout never rewrites line endings.
