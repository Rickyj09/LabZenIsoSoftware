import click

from app.services.document_migration_service import migrate_historical_document_files


@click.group(name="documentos")
def documentos_cli():
    """Operaciones administrativas del módulo documental."""


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
