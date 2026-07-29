import os
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

from app.services.storage_service import file_digest_and_size


class DocumentQrError(ValueError):
    pass


@dataclass(frozen=True)
class QrBox:
    page_selector: str
    normalized_box: tuple[float, float, float, float]


class DocumentQrService:
    def __init__(self, app=None):
        self.app = app or current_app

    def publication_box(self, tipo_documento=None):
        profile = self._profile_for_document_type(tipo_documento)
        page = (profile.get("page") or "first").strip().lower()
        raw_box = (profile.get("box") or "0.82,0.78,0.96,0.94").strip()
        parts = [part.strip() for part in raw_box.split(",")]
        if len(parts) != 4:
            raise DocumentQrError("DOCUMENT_PUBLICATION_QR_BOX debe tener cuatro coordenadas normalizadas.")
        try:
            box = tuple(float(part) for part in parts)
        except ValueError as exc:
            raise DocumentQrError("DOCUMENT_PUBLICATION_QR_BOX contiene coordenadas invalidas.") from exc
        self.validate_normalized_box(box)
        if page not in {"first", "last"}:
            try:
                if int(page) < 1:
                    raise ValueError
            except ValueError as exc:
                raise DocumentQrError("DOCUMENT_PUBLICATION_QR_PAGE debe ser first, last o un indice desde 1.") from exc
        return QrBox(page, box)

    def _profile_for_document_type(self, tipo_documento=None):
        profiles = self._configured_profiles()
        profile_name = (tipo_documento or "DEFAULT").strip().upper() or "DEFAULT"
        profile = {**profiles.get("DEFAULT", {}), **profiles.get(profile_name, {})}
        if profile_name:
            page_override = (self.app.config.get(f"DOCUMENT_PUBLICATION_QR_{profile_name}_PAGE") or "").strip()
            box_override = (self.app.config.get(f"DOCUMENT_PUBLICATION_QR_{profile_name}_BOX") or "").strip()
            if page_override:
                profile["page"] = page_override
            if box_override:
                profile["box"] = box_override
        return {
            "page": profile.get("page") or self.app.config.get("DOCUMENT_PUBLICATION_QR_PAGE") or "first",
            "box": profile.get("box") or self.app.config.get("DOCUMENT_PUBLICATION_QR_BOX") or "0.82,0.78,0.96,0.94",
            "profile": profile_name if profile_name in profiles else "DEFAULT",
        }

    def _configured_profiles(self):
        raw = self.app.config.get("DOCUMENT_PUBLICATION_QR_LAYOUT_PROFILES") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DocumentQrError("DOCUMENT_PUBLICATION_QR_LAYOUT_PROFILES debe ser JSON valido.") from exc
        profiles = {
            "DEFAULT": {
                "page": self.app.config.get("DOCUMENT_PUBLICATION_QR_PAGE") or "first",
                "box": self.app.config.get("DOCUMENT_PUBLICATION_QR_BOX") or "0.82,0.78,0.96,0.94",
            },
            "PROCEDIMIENTO": {
                "page": self.app.config.get("DOCUMENT_PUBLICATION_QR_PAGE") or "first",
                "box": self.app.config.get("DOCUMENT_PUBLICATION_QR_BOX") or "0.82,0.78,0.96,0.94",
            },
        }
        for name, profile in (raw or {}).items():
            if isinstance(profile, dict):
                profiles[str(name).strip().upper()] = {
                    "page": str(profile.get("page") or profiles["DEFAULT"]["page"]),
                    "box": str(profile.get("box") or profiles["DEFAULT"]["box"]),
                }
        return profiles

    def validate_normalized_box(self, box):
        x1, y1, x2, y2 = box
        if not all(0 <= value <= 1 for value in box):
            raise DocumentQrError("Las coordenadas del QR deben estar entre 0 y 1.")
        if x2 <= x1 or y2 <= y1:
            raise DocumentQrError("La caja del QR debe tener ancho y alto positivos.")
        return True

    def generate_qr_png(self, payload):
        payload = (payload or "").strip()
        if not payload:
            raise DocumentQrError("No se puede generar un QR sin URL de publicacion.")
        if "\\" in payload or "DOCUMENT_STORAGE_ROOT" in payload:
            raise DocumentQrError("El QR no debe contener rutas fisicas.")
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_M
        except Exception as exc:
            raise DocumentQrError("La dependencia qrcode[pil] no esta disponible.") from exc

        handle = tempfile.NamedTemporaryFile(prefix="labzeniso-qr-", suffix=".png", delete=False)
        path = Path(handle.name)
        handle.close()
        try:
            qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=12, border=4)
            qr.add_data(payload)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            image.save(path)
            sha256, size = file_digest_and_size(path)
            return path, sha256, size
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def embed_qr_in_pdf(self, *, pdf_path, qr_png_path, output_path=None, box: QrBox | None = None, tipo_documento=None):
        box = box or self.publication_box(tipo_documento=tipo_documento)
        output_path = Path(output_path) if output_path else Path(tempfile.NamedTemporaryFile(prefix="labzeniso-pdf-qr-", suffix=".pdf", delete=False).name)
        try:
            from pypdf import PdfReader, PdfWriter
            from reportlab.lib.utils import ImageReader
            from reportlab.pdfgen import canvas
        except Exception as exc:
            raise DocumentQrError("Las dependencias pypdf y reportlab son necesarias para insertar el QR.") from exc

        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            raise DocumentQrError("El PDF aprobado no contiene paginas.")
        page_index = self._resolve_page_index(box.page_selector, len(reader.pages))
        writer = PdfWriter()
        for index, page in enumerate(reader.pages):
            if index == page_index:
                width = float(page.cropbox.width)
                height = float(page.cropbox.height)
                x1, y1, x2, y2 = box.normalized_box
                left = float(page.cropbox.left) + x1 * width
                bottom = float(page.cropbox.bottom) + y1 * height
                qr_width = (x2 - x1) * width
                qr_height = (y2 - y1) * height
                overlay_path = self._overlay_pdf(qr_png_path, left, bottom, qr_width, qr_height, width, height)
                try:
                    overlay = PdfReader(str(overlay_path)).pages[0]
                    page.merge_page(overlay)
                finally:
                    overlay_path.unlink(missing_ok=True)
            writer.add_page(page)
        with output_path.open("wb") as output:
            writer.write(output)
        return output_path

    def _resolve_page_index(self, selector, page_count):
        if selector == "first":
            return 0
        if selector == "last":
            return page_count - 1
        index = int(selector) - 1
        if index < 0 or index >= page_count:
            raise DocumentQrError("La pagina configurada para QR no existe en el PDF.")
        return index

    def _overlay_pdf(self, image_path, left, bottom, width, height, page_width, page_height):
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        handle = tempfile.NamedTemporaryFile(prefix="labzeniso-qr-overlay-", suffix=".pdf", delete=False)
        path = Path(handle.name)
        handle.close()
        c = canvas.Canvas(str(path), pagesize=(page_width, page_height))
        c.drawImage(ImageReader(str(image_path)), left, bottom, width=width, height=height, preserveAspectRatio=True, mask="auto")
        c.save()
        return path
