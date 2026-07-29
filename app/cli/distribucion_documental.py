import click
from flask.cli import AppGroup

from app.services.document_email_service import DocumentEmailService


distribucion_documental_cli = AppGroup("distribucion-documental")


@distribucion_documental_cli.command("procesar-correos")
@click.option("--limite", default=50, show_default=True, type=int)
@click.option("--solo-fallidos", is_flag=True, default=False)
@click.option("--max-intentos", default=3, show_default=True, type=int)
@click.option("--publicacion-id", default=None, type=int)
def procesar_correos(limite, solo_fallidos, max_intentos, publicacion_id):
    """Procesa la cola transaccional de distribucion documental."""
    result = DocumentEmailService().process_pending(
        limite=limite,
        solo_fallidos=solo_fallidos,
        max_intentos=max_intentos,
        publicacion_id=publicacion_id,
    )
    click.echo(
        "Procesadas: {procesadas}. Enviadas: {enviadas}. Fallidas: {fallidas}.".format(**result)
    )
