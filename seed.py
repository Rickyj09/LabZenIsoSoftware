from app import create_app
from app.extensions import db
from app.models.empresa import Empresa
from app.models.seguridad import Usuario


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

    print("Proceso finalizado.")