from app import create_app
from app.extensions import db
from app.models.empresa import Empresa
from app.models.equipos import AreaAmbiente, Equipo, EquipoHistorial, Instalacion
from app.models.seguridad import Rol, Usuario, UsuarioRol


app = create_app()

with app.app_context():
    # 1. Crear empresa si no existe
    empresa = Empresa.query.filter_by(nombre="LabZen Demo").first()

    if not empresa:
        empresa = Empresa(
            nombre="LabZen Demo",
            ruc="9999999999001",
            email="admin@labzen.local",
            telefono="0999999999",
            direccion="Quito, Ecuador",
            ciudad="Quito",
            pais="Ecuador",
            plan="trial",
            estado="activo"
        )
        db.session.add(empresa)
        db.session.commit()
        print("Empresa creada.")
    else:
        print("La empresa ya existe.")

    # 2. Crear usuario admin si no existe
    usuario = Usuario.query.filter_by(username="admin").first()

    if not usuario:
        usuario = Usuario(
            empresa_id=empresa.id,
            nombre="Ricardo",
            apellido="Admin",
            email="admin@labzen.local",
            username="admin",
            cargo="Administrador",
            activo=True
        )
        usuario.set_password("Admin123*")

        db.session.add(usuario)
        db.session.commit()
        print("Usuario admin creado.")
    else:
        print("El usuario admin ya existe.")

    # 3. Garantizar que el usuario inicial tenga un rol administrativo.
    rol_administrador = Rol.query.filter(
        db.func.upper(Rol.nombre) == "ADMINISTRADOR"
    ).first()
    if not rol_administrador:
        rol_administrador = Rol(
            nombre="ADMINISTRADOR",
            descripcion="Rol administrador del sistema",
            es_sistema=True,
        )
        db.session.add(rol_administrador)
        db.session.flush()

    if not UsuarioRol.query.filter_by(
        usuario_id=usuario.id,
        rol_id=rol_administrador.id,
    ).first():
        db.session.add(UsuarioRol(usuario_id=usuario.id, rol_id=rol_administrador.id))
        db.session.commit()
        print("Rol ADMINISTRADOR asignado al usuario admin.")

    # 4. Datos minimos del paquete 5A para la empresa demo.
    instalacion = Instalacion.query.filter_by(
        empresa_id=empresa.id,
        codigo="LAB-DEMO-01",
    ).first()
    if not instalacion:
        instalacion = Instalacion(
            empresa_id=empresa.id,
            codigo="LAB-DEMO-01",
            nombre="Instalacion principal LabZen Demo",
            descripcion="Instalacion de demostracion para el modulo 5A.",
            direccion="Quito, Ecuador",
            responsable="Ricardo Admin",
            estado="activo",
        )
        db.session.add(instalacion)
        db.session.flush()
        print("Instalacion demo creada.")
    else:
        print("La instalacion demo ya existe.")

    areas_demo = [
        ("AREA-SUELOS", "Laboratorio de analisis de suelos", "Laboratorio", "Ala norte", True),
        ("AREA-RECEP", "Area de recepcion de muestras", "Recepcion", "Ingreso principal", False),
        ("AREA-BAL", "Area de balanzas", "Pesaje", "Sala climatizada", True),
    ]
    areas = {}
    for codigo, nombre, tipo, ubicacion, control in areas_demo:
        area = AreaAmbiente.query.filter_by(empresa_id=empresa.id, codigo=codigo).first()
        if not area:
            area = AreaAmbiente(
                empresa_id=empresa.id,
                instalacion_id=instalacion.id,
                codigo=codigo,
                nombre=nombre,
                tipo=tipo,
                ubicacion_interna=ubicacion,
                responsable="Ricardo Admin",
                requiere_control_ambiental=control,
                estado="activo",
            )
            db.session.add(area)
            db.session.flush()
        areas[codigo] = area

    equipos_demo = [
        ("EQ-BAL-001", "Balanza analitica", "Balanza", "Mettler Toledo", "XPR", "SN-BAL-001", "AREA-BAL", "OPERATIVO", "ALTA", True, True),
        ("EQ-EST-001", "Estufa de secado", "Estufa", "Memmert", "UF55", "SN-EST-001", "AREA-SUELOS", "EN_MANTENIMIENTO", "MEDIA", False, True),
        ("EQ-PH-001", "Potenciometro pH", "Medidor", "Hanna", "HI5221", "SN-PH-001", "AREA-SUELOS", "EN_CALIBRACION", "ALTA", True, True),
        ("EQ-REF-001", "Refrigerador de muestras", "Refrigeracion", "Indurama", "RI-480", "SN-REF-001", "AREA-RECEP", "OPERATIVO", "MEDIA", False, True),
        ("EQ-MIC-001", "Microscopio retirado", "Microscopio", "Olympus", "CX23", "SN-MIC-001", "AREA-SUELOS", "RETIRADO", "BAJA", False, False),
    ]
    for codigo, nombre, tipo, marca, modelo, serie, area_codigo, estado_operativo, criticidad, requiere_cal, requiere_mant in equipos_demo:
        equipo = Equipo.query.filter_by(empresa_id=empresa.id, codigo=codigo).first()
        if equipo:
            continue
        area = areas[area_codigo]
        equipo = Equipo(
            empresa_id=empresa.id,
            codigo=codigo,
            nombre=nombre,
            tipo=tipo,
            marca=marca,
            modelo=modelo,
            serie=serie,
            instalacion_id=instalacion.id,
            area_ambiente_id=area.id,
            ubicacion_especifica=area.ubicacion_interna,
            responsable="Ricardo Admin",
            estado="activo",
            estado_operativo=estado_operativo,
            criticidad=criticidad,
            requiere_calibracion=requiere_cal,
            requiere_mantenimiento=requiere_mant,
            observaciones="Dato de demostracion del paquete 5A.",
        )
        db.session.add(equipo)
        db.session.flush()
        db.session.add(EquipoHistorial(
            empresa_id=empresa.id,
            equipo_id=equipo.id,
            tipo_evento="CREACION",
            estado_nuevo=estado_operativo,
            descripcion="Equipo demo creado por seed.",
            usuario_id=usuario.id,
        ))
    db.session.commit()
    print("Datos demo del paquete 5A verificados.")

    print("Proceso finalizado.")
