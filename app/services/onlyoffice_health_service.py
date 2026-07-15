import ssl
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from flask import current_app


@dataclass(frozen=True)
class OnlyOfficeHealthResult:
    enabled: bool
    available: bool
    status_code: int | None = None
    url: str | None = None
    message: str = ""

    def to_dict(self):
        return asdict(self)


class OnlyOfficeHealthService:
    def __init__(self, app=None):
        self.app = app or current_app

    def check(self):
        if not self.app.config.get("ONLYOFFICE_ENABLED"):
            return OnlyOfficeHealthResult(
                enabled=False,
                available=False,
                message="Integración ONLYOFFICE deshabilitada",
            )

        base_url = self.app.config["ONLYOFFICE_INTERNAL_URL"].rstrip("/") + "/"
        health_path = self.app.config["ONLYOFFICE_HEALTHCHECK_PATH"].lstrip("/")
        health_url = urljoin(base_url, health_path)
        timeout = int(self.app.config["ONLYOFFICE_REQUEST_TIMEOUT_SECONDS"])
        verify_ssl = bool(self.app.config["ONLYOFFICE_VERIFY_SSL"])

        context = None
        if health_url.startswith("https://") and not verify_ssl:
            context = ssl._create_unverified_context()

        request = Request(health_url, method="GET", headers={"User-Agent": "LabZenISO-OnlyOffice-Health/1.0"})
        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                status_code = response.getcode()
        except HTTPError as exc:
            return OnlyOfficeHealthResult(
                enabled=True,
                available=False,
                status_code=exc.code,
                url=health_url,
                message=f"ONLYOFFICE respondió con estado HTTP {exc.code}",
            )
        except TimeoutError:
            return OnlyOfficeHealthResult(
                enabled=True,
                available=False,
                url=health_url,
                message="Timeout consultando ONLYOFFICE",
            )
        except URLError as exc:
            return OnlyOfficeHealthResult(
                enabled=True,
                available=False,
                url=health_url,
                message=f"No se pudo conectar con ONLYOFFICE: {exc.reason}",
            )
        except OSError as exc:
            return OnlyOfficeHealthResult(
                enabled=True,
                available=False,
                url=health_url,
                message=f"No se pudo consultar ONLYOFFICE: {exc}",
            )

        return OnlyOfficeHealthResult(
            enabled=True,
            available=200 <= status_code < 300,
            status_code=status_code,
            url=health_url,
            message="ONLYOFFICE disponible" if 200 <= status_code < 300 else "ONLYOFFICE no disponible",
        )
