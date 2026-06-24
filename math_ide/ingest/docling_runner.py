"""Optional live PDF -> Docling-JSON conversion (lazy import).

Docling (and its torch dependency) is a heavy optional dependency. This module
isolates the only code that touches it behind a lazy ``import docling`` *inside*
:func:`run_docling`, so importing this module is always safe — even in the test
environment where Docling is not installed. Tests never call :func:`run_docling`;
they feed the adapter a Docling JSON dict directly.

Mirrors ``pdf_to_docling.py``'s converter setup (OCR + formula enrichment
toggles) but returns the raw ``export_to_dict()`` mapping instead of a string.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any


def run_docling(
    source: str | Path,
    *,
    ocr: bool = False,
    formula: bool = True,
) -> dict[str, Any]:
    """Convert a PDF path/URL/stdin-stream into a Docling document dict.

    Imports Docling lazily so the surrounding package stays importable without
    it. ``formula`` enables formula enrichment (LaTeX), ``ocr`` enables OCR.
    Returns ``document.export_to_dict()`` — the exact shape the adapter
    consumes.

    Raises :class:`RuntimeError` if Docling is not installed, or
    :class:`FileNotFoundError` for a missing local path.
    """
    try:  # lazy: keep the module importable when docling is absent
        from docling.datamodel.base_models import (
            ConversionStatus,
            DocumentStream,
            InputFormat,
        )
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:  # pragma: no cover - exercised only with docling
        raise RuntimeError(
            "Docling is not installed. Install the optional ingest extras "
            "(see requirements-ingest.txt) to convert PDFs live, or pass a "
            "pre-converted Docling JSON dict."
        ) from exc

    resolved = _resolve_source(source, DocumentStream)

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=PdfPipelineOptions(
                    do_ocr=ocr,
                    do_formula_enrichment=formula,
                ),
            ),
        },
    )
    result = converter.convert(resolved)
    if result.status != ConversionStatus.SUCCESS:  # pragma: no cover
        messages = [err.error_message for err in result.errors]
        raise RuntimeError(
            f"Docling conversion failed ({result.status.name}): "
            + ("; ".join(messages) if messages else "unknown error")
        )
    return result.document.export_to_dict()


def _resolve_source(source: str | Path, document_stream_cls):
    """Resolve a source argument into something the converter accepts."""
    if isinstance(source, str) and source.startswith(("http://", "https://")):
        return source
    path = Path(source)
    if not path.is_file():  # pragma: no cover - depends on local fs
        raise FileNotFoundError(f"PDF not found: {path}")
    return path
