import click

from app.services.document_demo_seed_service import seed_demo_documents
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
