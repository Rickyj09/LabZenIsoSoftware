from app.models.empresa import Empresa, Sede
from app.models.seguridad import Usuario, Rol, Permiso, UsuarioRol, RolPermiso
from app.models.clientes import Cliente, Solicitud
from app.models.laboratorio import (
    Muestra,
    EnsayoCatalogo,
    Metodo,
    MetodoParametro,
    EnsayoMetodo,
    MuestraEnsayo,
    Resultado,
    CadenaCustodia,
)
from app.models.equipos import (
    AreaCondicionAmbiental,
    AreaHistorialAmbiental,
    AreaAmbiente,
    AreaMedicionAmbiental,
    Equipo,
    EquipoCalibracion,
    EquipoCalibracionDocumento,
    EquipoDocumento,
    EquipoHistorial,
    EquipoMantenimiento,
    EquipoMantenimientoDocumento,
    EquipoPlanMantenimiento,
    Instalacion,
    MaterialReferencia,
    MaterialReferenciaDocumento,
    MaterialReferenciaHistorial,
)
from app.models.documentos import (
    CarpetaDocumental,
    Documento,
    DocumentoVersion,
    DocumentoVersionAnexo,
    DocumentoVigorCatalogo,
    DocumentoAprobacion,
    DocumentoSnapshot,
    DocumentoArtefacto,
    DocumentoConversion,
    DocumentoFirmaEvento,
    DocumentoFirmaPaso,
    DocumentoFirmaProceso,
    DocumentoPublicacion,
    DocumentoDistribucionDestinatario,
    DocumentoDistribucionEntrega,
    DocumentoEdicion,
    DocumentoEdicionEvento,
    UsuarioIdentidadFirma,
)
from app.models.calidad import NoConformidad, AccionCorrectiva, Riesgo, PersonalCompetencia
from app.models.auditoria import Auditoria, AuditoriaHallazgo, AuditoriaLog
from app.models.organigrama import (
    Cargo,
    PerfilPuesto,
    Personal,
    PersonalCalificacion,
    PersonalCalificacionEvidencia,
    PersonalExperiencia,
)
from app.models.mapa_procesos import Proceso
from app.models.ofertas import Oferta
from app.models.contratos import Contrato
