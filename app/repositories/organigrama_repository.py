from app.models.organigrama import Personal

def obtener_personal():
    return Personal.query.all()