from math import ceil
from pathlib import Path
from shutil import rmtree

import pypdfium2 as pdfium


class PreviewRenderError(Exception):
    pass


def render_pdf_previews(
    source: Path,
    destination: Path,
    *,
    scale: float,
    max_pixels: int = 25_000_000,
    max_bytes: int = 512 * 1024 * 1024,
) -> int:
    if scale <= 0 or max_pixels <= 0 or max_bytes <= 0:
        raise ValueError("Preview limits must be greater than zero.")
    if not source.is_file():
        raise PreviewRenderError("Source PDF does not exist.")

    destination.mkdir(parents=True, exist_ok=False)
    document: pdfium.PdfDocument | None = None
    try:
        document = pdfium.PdfDocument(source)
        page_count = len(document)
        if page_count < 1:
            raise PreviewRenderError("PDF does not contain any pages.")

        total_bytes = 0
        for index in range(page_count):
            page = document[index]
            bitmap = None
            image = None
            converted = None
            try:
                width, height = page.get_size()
                rendered_pixels = ceil(width * scale) * ceil(height * scale)
                if rendered_pixels > max_pixels:
                    raise PreviewRenderError("PDF page exceeds the preview pixel limit.")
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                converted = image.convert("RGB")
                converted.save(
                    destination / f"page-{index + 1:04d}.png",
                    format="PNG",
                    compress_level=6,
                )
                total_bytes += (
                    destination / f"page-{index + 1:04d}.png"
                ).stat().st_size
                if total_bytes > max_bytes:
                    raise PreviewRenderError("PDF previews exceed the size limit.")
            finally:
                if converted is not None:
                    converted.close()
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                page.close()
        return page_count
    except PreviewRenderError:
        rmtree(destination, ignore_errors=True)
        raise
    except Exception as error:
        rmtree(destination, ignore_errors=True)
        raise PreviewRenderError("PDF preview rendering failed.") from error
    finally:
        if document is not None:
            document.close()
