"""admin.converters — conversion and packaging tools (admin / full runtime).

These modules depend on optional heavy deps (text-fabric, context-fabric,
under the `[full]` extra) and are intended for dataset ingestion / admin
tooling only.

Pipeline: a `_{format}_to_tf.py` converter turns a source document into a
Text-Fabric dataset; `convert_to_cfm` compiles that into Context-Fabric's
`.cfm` cache; `convert_to_corpus` packages both into a `.corpus` archive.
"""

from ..parsers import SourceFormat
from ._epub_to_tf import convert_epub_to_tf
from ._html_to_tf import convert_html_to_tf
from ._pdf_to_tf import convert_pdf_to_tf
from ._tei_to_tf import convert_tei_to_tf
from ._tei_zip_to_tf import convert_tei_zip_to_tf
from ._text_to_tf import convert_text_to_tf
from ._tf_zip_to_tf import convert_tf_zip_to_tf
from ._xml_to_tf import convert_xml_to_tf
from .convert_to_cfm import convert_to_cfm
from .convert_to_corpus import CorpusArchiveError, convert_to_corpus

CONVERTERS = {
    SourceFormat.EPUB: convert_epub_to_tf,
    SourceFormat.HTML: convert_html_to_tf,
    SourceFormat.XML: convert_xml_to_tf,
    SourceFormat.PDF: convert_pdf_to_tf,
    SourceFormat.TEI: convert_tei_to_tf,
    SourceFormat.TEI_ZIP: convert_tei_zip_to_tf,
    SourceFormat.PLAIN: convert_text_to_tf,
    SourceFormat.TF_ZIP: convert_tf_zip_to_tf,
}

__all__ = [
    "CONVERTERS",
    "CorpusArchiveError",
    "convert_epub_to_tf",
    "convert_html_to_tf",
    "convert_pdf_to_tf",
    "convert_tei_to_tf",
    "convert_tei_zip_to_tf",
    "convert_text_to_tf",
    "convert_tf_zip_to_tf",
    "convert_xml_to_tf",
    "convert_to_cfm",
    "convert_to_corpus",
]
