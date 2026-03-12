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
from app.models.equipos import Equipo, EquipoCalibracion, EquipoMantenimiento, EquipoDocumento
from app.models.documentos import Documento, DocumentoVersion, DocumentoAprobacion
from app.models.calidad import NoConformidad, AccionCorrectiva, Riesgo, PersonalCompetencia
from app.models.auditoria import Auditoria, AuditoriaHallazgo, AuditoriaLog
from app.models.organigrama import Cargo, Personal
from app.models.mapa_procesos import Proceso