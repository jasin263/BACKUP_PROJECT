import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix

# Set up logger
logger = logging.getLogger(__name__)

# Create SQLAlchemy base class
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy
db = SQLAlchemy(model_class=Base)

# Create Flask application
app = Flask(__name__)

# Configure secret key
app.secret_key = os.environ.get("SESSION_SECRET", "default-backup-secret-key")

# Configure proxy settings for proper URL generation
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure database connection
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///backup_app.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize database with the application
db.init_app(app)

# Set up Flask-Login manager
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Import routes after app is created to avoid circular imports
from backup_app.scheduler import init_scheduler

with app.app_context():
    # Import models
    import models
    
    # Create all database tables
    db.create_all()
    
    # Initialize scheduler
    init_scheduler()
    
    # Import routes
    import auth
    import transfer
    
    @login_manager.user_loader
    def load_user(user_id):
        return models.User.query.get(int(user_id))
