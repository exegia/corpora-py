# Synthetic PDF source fixture

`outlined.pdf` was authored locally with ReportLab for conversion tests. It has
two pages, nested outline entries, a small blue raster image on each page, and
English, decomposed Latin accents and Greek text. Its embedded DejaVu Sans font
comes from the bundled runtime. No private book content is included.

Tests compare native MuPDF extraction, image placements and source bytes against
the exported package. This fixture does not establish arbitrary PDF layout or
OCR fidelity.
