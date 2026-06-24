# math-ide

Convert PDF documents to structured text using [Docling](https://github.com/docling-project/docling). The CLI accepts a local file path, a URL, or raw PDF bytes from stdin and exports markdown, JSON, or LaTeX.

## Requirements

- Python 3.10+
- Enough disk space for Docling and its model dependencies (PyTorch, layout models, etc.)

## Setup

```bash
cd ~/Projects/math-ide
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The first conversion downloads layout models from Hugging Face. That one-time step can take several minutes; later runs are much faster.

## Usage

### Local PDF

```bash
python pdf_to_docling.py document.pdf
```

### URL

```bash
python pdf_to_docling.py https://arxiv.org/pdf/2408.09869
```

### Stdin pipe

```bash
cat document.pdf | python pdf_to_docling.py
curl -fsSL https://example.com/doc.pdf | python pdf_to_docling.py
```

### Write to a file

```bash
python pdf_to_docling.py document.pdf -o output.md
```

### Export JSON

```bash
python pdf_to_docling.py document.pdf --format json -o output.json
```

### Export LaTeX

```bash
python pdf_to_docling.py document.pdf --format latex -o output.tex
```

For math-heavy PDFs, enable formula recognition so equations are emitted as LaTeX instead of placeholders:

```bash
python pdf_to_docling.py document.pdf --format latex --formula -o output.tex
```

The LaTeX output is a complete `.tex` file (preamble plus `\begin{document}` … `\end{document}`). Compile it with an external tool such as `pdflatex` or `tectonic`.

### Scanned PDFs (OCR)

OCR is disabled by default for faster processing of text-based PDFs. Enable it for scanned or image-only documents:

```bash
python pdf_to_docling.py scan.pdf --ocr
```

## Options

| Option | Description |
| --- | --- |
| `pdf` | Optional path or URL to a PDF. Omit when piping bytes on stdin. |
| `-o`, `--output` | Write output to a file instead of stdout. |
| `--format` | `markdown` (default), `json`, or `latex`. |
| `--ocr` | Enable OCR for scanned/image PDFs. |
| `--formula` | Recognize formulas and convert them to LaTeX (slower). |

## Examples

```bash
# Markdown to stdout
python pdf_to_docling.py example.pdf

# JSON to a file
python pdf_to_docling.py example.pdf --format json -o result.json

# LaTeX with formula recognition
python pdf_to_docling.py example.pdf --format latex --formula -o result.tex

# Pipe into another tool
python pdf_to_docling.py paper.pdf | less
```

## Project layout

```
math-ide/
├── pdf_to_docling.py   # CLI entry point
├── requirements.txt
├── .gitignore
└── README.md
```

Generated artifacts (`.venv/`, `output/`, conversion results) are gitignored.

## Notes

- **Text PDFs:** leave OCR off for best speed on documents with an embedded text layer.
- **Scanned PDFs:** pass `--ocr`. OCR is slower and may require additional runtime dependencies depending on your Docling/OCR engine configuration.
- **Formulas:** pass `--formula` to decode equations to LaTeX (in markdown as `$...$` / `$$...$$`, in LaTeX export as math environments). Without it, formulas appear as placeholders.
- **URLs:** the argument must start with `http://` or `https://`.

## License

Docling is MIT-licensed. See the [Docling repository](https://github.com/docling-project/docling) for details.
