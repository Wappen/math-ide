#!/usr/bin/env python3
"""Read a PDF file (or stdin) and convert it with Docling."""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from docling.datamodel.base_models import ConversionStatus, DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a PDF to structured output using Docling.",
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        help="Path or URL to a PDF file. Omit to read PDF bytes from stdin.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write output to this file instead of stdout.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Export format (default: markdown).",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR for scanned/image PDFs (slower; off by default).",
    )
    return parser


def build_converter(use_ocr: bool) -> DocumentConverter:
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=PdfPipelineOptions(do_ocr=use_ocr),
            ),
        },
    )


def read_pdf_source(pdf: str | None) -> Path | str | DocumentStream:
    if pdf is not None:
        if pdf.startswith(("http://", "https://")):
            return pdf
        pdf_path = Path(pdf)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        return pdf_path

    if sys.stdin.isatty():
        raise SystemExit(
            "No PDF path given and stdin is empty. "
            "Pass a file path or pipe PDF bytes: cat doc.pdf | python pdf_to_docling.py"
        )

    data = sys.stdin.buffer.read()
    if not data:
        raise SystemExit("stdin was empty; nothing to convert.")

    return DocumentStream(name="stdin.pdf", stream=BytesIO(data))


def export_document(document, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(document.export_to_dict(), indent=2)
    return document.export_to_markdown()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = read_pdf_source(args.pdf)

    converter = build_converter(args.ocr)
    result = converter.convert(source)

    if result.status != ConversionStatus.SUCCESS:
        messages = [err.error_message for err in result.errors]
        raise SystemExit(
            f"Conversion failed ({result.status.name}): "
            + ("; ".join(messages) if messages else "unknown error")
        )

    output = export_document(result.document, args.format)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
