# Local resume OCR

Install the backend AI extra with `uv sync --extra ai --extra dev`. The lockfile includes
RapidOCR's bundled ONNX models, ONNX Runtime CPU and PDFium. No system Tesseract or
paid vision API is required. Package installation downloads software/models once;
document processing runs locally. The OCR child disables Python socket connections.

Text PDFs use existing extraction. If any page has fewer than 80 readable characters,
the bounded OCR worker keeps readable pages and renders the short-text pages locally.
PNG/JPEG photos are also supported. Public application uploads normalize photos to PDF
in memory and retain the existing private S3 receipt/access-control path; the original
image file/metadata is not retained separately. Staff-uploaded PNG/JPEG resumes are
read directly. DOCX/TXT keep existing text extraction. Legacy DOC is not supported.

Limits: 5 MB input, 30 PDF pages, at most 10 OCR pages, 20-megapixel source images,
2400-pixel rendered longest side, 60,000 extracted characters and 120-second subprocess
timeout. Images must be single PNG/JPEG frames. Low-confidence OCR lines are filtered;
unreadable scanned pages fail with a review/reupload message instead of silently
producing a partial assessment. Blank pages may need removal. Use clear upright printed
resumes; handwriting, complex columns and languages beyond the bundled model's coverage
are not guaranteed. Image classification corrects supported line rotation, not every
camera perspective. No temporary candidate files are written; input and output use pipes.

Assessment results retain extraction method/OCR page numbers, and the recruiter sees
a warning to verify OCR text against the original document. Names, dates and evidence
can still be misread. OCR failure occurs before the screening provider call. Normal
downstream AI assessment continues to consume tokens; OCR itself makes no paid API call.

Verification: `pytest tests/test_local_ocr.py -q` runs actual bundled OCR offline on
synthetic images and a mixed text/scanned PDF, plus native-text bypass, unreadable image,
timeout/page-limit and private public-upload tests.

References: [RapidOCR API](https://rapidai.github.io/RapidOCRDocs/v1.4.4/install_usage/api/RapidOCR/),
[PDFium Python API](https://pypdfium2.readthedocs.io/en/stable/python_api.html).
