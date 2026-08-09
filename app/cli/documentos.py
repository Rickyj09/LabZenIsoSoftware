import click

from app.models.documentos import CONVERSION_EN_PROCESO, CONVERSION_PENDIENTE, CONVERSION_SOLICITADA, DocumentoConversion
from app.services.document_pdf_service import DocumentPdfError, DocumentPdfService
from app.services.document_signature_service import DocumentSignatureService
from app.services.document_demo_seed_service import seed_demo_documents
from app.services.document_migration_service import migrate_historical_document_files
from app.services.document_vigor_import_service import DocumentVigorImportError, DocumentVigorImportService


@click.group(name="documentos")
def documentos_cli():
    """Operaciones administrativas del módulo documental."""


@documentos_cli.command(name="importar-vigor")
@click.option("--empresa-id", required=True, type=int, help="Empresa destino de la importacion.")
@click.option("--internos", "internos_path", required=True, type=click.Path(exists=True, dir_okay=False), help="Ruta del Excel de documentos internos.")
@click.option("--externos", "externos_path", required=True, type=click.Path(exists=True, dir_okay=False), help="Ruta del Excel de documentos externos.")
@click.option("--formatos", "formatos_path", required=True, type=click.Path(exists=True, dir_okay=False), help="Ruta del Excel de formatos.")
@click.option(
    "--password",
    envvar="DOCUMENTOS_VIGOR_EXCEL_PASSWORD",
    help="Contrasena de los libros protegidos. Tambien puede venir de DOCUMENTOS_VIGOR_EXCEL_PASSWORD.",
)
@click.option("--usuario-id", type=int, default=None, help="Usuario que queda registrado como importador/actualizador.")
def importar_vigor(empresa_id, internos_path, externos_path, formatos_path, password, usuario_id):
    """Importa listados de documentos y formatos en vigor desde Excel."""
    try:
        result = DocumentVigorImportService().import_excel_files(
            empresa_id=empresa_id,
            internos_path=internos_path,
            externos_path=externos_path,
            formatos_path=formatos_path,
            password=password,
            usuario_id=usuario_id,
        )
    except DocumentVigorImportError as exc:
        raise click.ClickException(str(exc)) from exc

    for summary in result.summaries:
        click.echo(
            f"{summary.tipo_listado}: "
            f"insertados={summary.insertados}, "
            f"actualizados={summary.actualizados}, "
            f"omitidos={summary.omitidos}, "
            f"advertencias={len(summary.advertencias)}, "
            f"errores={len(summary.errores)}, "
            f"hoja={summary.fuente_hoja}"
        )
        for warning in summary.advertencias:
            click.echo(f"  advertencia: {warning}")
        for error in summary.errores:
            click.echo(f"  error: {error}")
    click.echo(
        "Total: "
        f"insertados={result.insertados}, "
        f"actualizados={result.actualizados}, "
        f"omitidos={result.omitidos}, "
        f"advertencias={len(result.advertencias)}, "
        f"errores={len(result.errores)}"
    )


@documentos_cli.command(name="migrar-archivos-historicos")
@click.option("--dry-run", is_flag=True, help="Simula la migración sin copiar ni actualizar datos.")
@click.option("--apply", "apply_changes", is_flag=True, help="Copia archivos y actualiza metadatos.")
def migrar_archivos_historicos(dry_run, apply_changes):
    """Migra archivos documentales públicos al storage privado."""
    if dry_run and apply_changes:
        raise click.UsageError("Usa --dry-run o --apply, no ambos.")

    effective_dry_run = not apply_changes
    if not dry_run and not apply_changes:
        click.echo("No se indicó --apply; se ejecutará en modo simulación.")

    summary = migrate_historical_document_files(
        apply=apply_changes,
        reporter=click.echo,
    )
    click.echo(
        "Resumen: "
        f"encontrados={summary.encontrados}, "
        f"simulados={summary.simulados}, "
        f"migrados={summary.migrados}, "
        f"omitidos={summary.omitidos}, "
        f"no_encontrados={summary.no_encontrados}, "
        f"errores={summary.errores}."
    )
    if effective_dry_run:
        click.echo("Simulación finalizada: no se copiaron archivos ni se modificó la base de datos.")
    if summary.errores:
        raise click.ClickException("La migración terminó con errores; revisa el detalle anterior.")
@documentos_cli.command(name="conversiones-pendientes")
@click.option("--procesar", is_flag=True, help="Reanuda conversiones pendientes/en proceso.")
def conversiones_pendientes(procesar):
    """Lista o reanuda conversiones PDF aprobadas pendientes."""
    conversiones = (
        DocumentoConversion.query
        .filter(DocumentoConversion.estado.in_((CONVERSION_PENDIENTE, CONVERSION_SOLICITADA, CONVERSION_EN_PROCESO)))
        .order_by(DocumentoConversion.solicitado_en.asc(), DocumentoConversion.id.asc())
        .all()
    )
    if not conversiones:
        click.echo("No existen conversiones pendientes.")
        return
    service = DocumentPdfService()
    for conversion in conversiones:
        click.echo(
            f"{conversion.public_id} estado={conversion.estado} "
            f"documento={conversion.documento_id} version={conversion.documento_version_id} "
            f"attempt={conversion.attempt_number} percent={conversion.percent or 0}"
        )
        if procesar:
            try:
                artifact = service.process_conversion(conversion=conversion)
                click.echo(
                    f"  procesada: artefacto={artifact.public_id if artifact else '-'} "
                    f"estado={artifact.estado if artifact else '-'}"
                )
            except DocumentPdfError as exc:
                click.echo(f"  error controlado: {exc}")


@documentos_cli.command(name="firmas-vencidas")
def firmas_vencidas():
    """Marca procesos de firma digital externa vencidos."""
    total = DocumentSignatureService().expire_due_processes(reporter=click.echo)
    click.echo(f"Procesos de firma vencidos actualizados: {total}.")


@documentos_cli.command(name="seed-demo")
@click.option("--empresa-id", default=1, show_default=True, type=int, help="Empresa donde se crearán los datos demo.")
def seed_demo(empresa_id):
    """Crea datos demo idempotentes para el módulo documental."""
    summary = seed_demo_documents(empresa_id=empresa_id)
    click.echo(f"Datos demo documentales listos para empresa_id={summary['empresa_id']}.")
    click.echo("Documentos demo: " + ", ".join(summary["document_codes"]))
    click.echo("Usuarios demo: " + ", ".join(summary["usernames"]))
    if summary["created_documents"]:
        click.echo("Creados en esta ejecución: " + ", ".join(summary["created_documents"]))
    else:
        click.echo("No se duplicaron documentos; los códigos demo ya existían.")
