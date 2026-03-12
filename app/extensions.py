from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "web_auth.login"
login_manager.login_message = "Debes iniciar sesión para continuar."
login_manager.login_message_category = "warning"