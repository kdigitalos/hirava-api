"""Bounded local OCR. Worker input/output use pipes, never candidate files."""
from io import BytesIO
import json
import subprocess
import sys

MAX_PIXELS = 20_000_000


def load_image(content):
    from PIL import Image, ImageOps
    image = Image.open(BytesIO(content))
    if image.format not in ("PNG", "JPEG") or getattr(image, "n_frames", 1) != 1:
        image.close()
        raise ValueError("Use a single PNG or JPEG image")
    if image.width * image.height > MAX_PIXELS:
        image.close()
        raise ValueError("Resume image must be at most 20 megapixels")
    oriented = ImageOps.exif_transpose(image)
    rgba = oriented.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    result = background.convert("RGB")
    background.close()
    rgba.close()
    oriented.close()
    image.close()
    return result


def image_pdf(content):
    """Normalize public photo uploads into the existing private PDF storage path."""
    image = load_image(content)
    try:
        image.thumbnail((2400, 2400))
        output = BytesIO()
        image.save(output, format="PDF", resolution=200)
        return output.getvalue()
    finally:
        image.close()


def local_ocr(content, suffix):
    from app.agents.screening import ScreeningError
    try:
        response = subprocess.run([sys.executable, "-m", "app.agents.ocr", suffix], input=content,
            capture_output=True, timeout=120, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = json.loads(response.stdout)
        if response.returncode or "error" in result:
            raise ScreeningError(result.get("error", "Local OCR failed. Upload a clearer resume."))
        return result
    except subprocess.TimeoutExpired:
        raise ScreeningError("Local OCR exceeded 120 seconds. Upload a shorter or clearer resume.") from None
    except ScreeningError:
        raise
    except Exception:
        raise ScreeningError("Local OCR is unavailable. Install the AI dependencies and retry.") from None


def recognize(content, suffix):
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR(text_score=0.6, intra_op_num_threads=2, inter_op_num_threads=1)

    def read_image(image):
        image.thumbnail((2400, 2400))
        # RapidOCR ndarray input follows OpenCV's BGR convention.
        rows, _ = engine(np.asarray(image.convert("RGB"))[:, :, ::-1].copy())
        return "\n".join(str(row[1]) for row in rows or [] if float(row[2]) >= 0.6)

    pages, ocr_pages = [], []
    if suffix in (".png", ".jpg", ".jpeg"):
        image = load_image(content)
        try:
            pages.append(read_image(image))
        finally:
            image.close()
        ocr_pages.append(1)
    elif suffix == ".pdf":
        from pypdf import PdfReader
        import pypdfium2 as pdfium
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or len(reader.pages) > 30:
            raise ValueError("PDF must be unencrypted and at most 30 pages")
        pdf = pdfium.PdfDocument(content)
        try:
            for index, source in enumerate(reader.pages):
                native = source.extract_text() or ""
                if len(native.strip()) >= 80:
                    pages.append(native)
                    continue
                if len(ocr_pages) >= 10:
                    raise ValueError("OCR supports at most 10 scanned pages per resume")
                page = pdf[index]
                bitmap = image = None
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ValueError("Invalid PDF page size")
                    scale = min(200 / 72, 2400 / max(width, height))
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil().convert("RGB")
                    text = read_image(image)
                    if len(text.strip()) < 20:
                        raise ValueError("A scanned page is unreadable. Upload a clearer resume or remove blank pages.")
                    pages.append(text)
                    ocr_pages.append(index + 1)
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
                if sum(map(len, pages)) > 60000:
                    raise ValueError("Resume exceeds 60,000 extracted characters")
        finally:
            pdf.close()
    else:
        raise ValueError("Unsupported OCR format")
    text = "\n".join(pages)
    if not 50 <= len(text.strip()) <= 60000:
        raise ValueError("Insufficient readable text or extraction limit exceeded. Upload a clearer, shorter resume.")
    return {"text": text, "method": "local_ocr", "ocr_pages": ocr_pages, "engine": "rapidocr-cpu"}


def main():
    # Bundled models only: an OCR worker must never fetch files or send documents.
    import socket
    from contextlib import redirect_stdout
    def offline(*args, **kwargs):
        raise OSError("OCR network access disabled")
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    content = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
    try:
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("Resume exceeds 5 MB")
        with redirect_stdout(sys.stderr):
            result = recognize(content, sys.argv[1])
    except ImportError:
        result = {"error": "Local OCR is not installed. Install the backend AI dependencies."}
    except ValueError as exc:
        # Only our own validation messages; never echo third-party payloads.
        safe = str(exc)
        allowed = ("Use a single", "Resume image", "PDF must", "OCR supports", "Invalid PDF", "A scanned page", "Resume exceeds", "Insufficient readable")
        result = {"error": safe if safe.startswith(allowed) else "Local OCR could not read this document. Upload a clearer resume."}
    except Exception:
        result = {"error": "Local OCR could not read this document. Upload a clearer resume."}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode("utf-8"))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
