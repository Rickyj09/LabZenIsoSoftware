import click

from app.services.document_signature_dev_service import (
    DocumentSignatureDevCertificateService,
    DocumentSignatureDevError,
)


@click.group(name="firmas-dev")
def firmas_dev_cli():
    """Herramientas locales de desarrollo para firmas PAdES de prueba."""


@firmas_dev_cli.command(name="inicializar")
@click.option("--regenerar", is_flag=True, help="Regenera la CA y los certificados locales de desarrollo.")
@click.option(
    "--confirmar-proceso-activo",
    is_flag=True,
    help="Permite regenerar aunque existan procesos EN_FIRMA activos.",
)
def inicializar(regenerar, confirmar_proceso_activo):
    """Inicializa CA/certificados locales y sincroniza identidades de firma."""
    try:
        result = DocumentSignatureDevCertificateService().initialize(
            regenerate=regenerar,
            confirm_active_process=confirmar_proceso_activo,
            reporter=click.echo,
        )
    except DocumentSignatureDevError as exc:
        raise click.ClickException(str(exc)) from exc

    if result["created"]:
        click.echo("Certificados creados: " + ", ".join(result["created"]))
    else:
        click.echo("Certificados ya existentes; no se duplicaron.")
    click.echo("CA creada/lista: " + result["ca_certificate"])
    click.echo("Sincronizacion finalizada sin imprimir claves privadas ni contrasenas.")
