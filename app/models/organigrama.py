from app.extensions import db

class Cargo(db.Model):
    __tablename__ = "cargos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)

class Personal(db.Model):
    __tablename__ = "personal"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    cargo_id = db.Column(db.Integer, db.ForeignKey("cargos.id"))
    email = db.Column(db.String(150))
    telefono = db.Column(db.String(50))
    activo = db.Column(db.Boolean, default=True)

    cargo = db.relationship("Cargo")