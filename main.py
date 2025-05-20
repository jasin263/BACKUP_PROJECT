import os
import sys
import logging
import django

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Import Django WSGI application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backup_project.settings')
django.setup()

# Import Django models
from django.db import connection
from django.db.utils import ProgrammingError, OperationalError
from django.core.wsgi import get_wsgi_application

# This is what Gunicorn looks for
app = application = get_wsgi_application()

# Initialize the scheduler only if the database is ready
def initialize_app():
    try:
        # Check if database tables exist by running a simple query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM django_migrations LIMIT 1")
            
        # If we reach this point, tables exist, so initialize scheduler
        from backup_app.scheduler import init_scheduler
        init_scheduler()
        logging.info("Scheduler initialized successfully")
        
    except (ProgrammingError, OperationalError) as e:
        # Tables don't exist yet, migrations need to be run
        logging.warning(f"Database not ready: {e}")
        logging.warning("Run 'python manage.py migrate' to set up the database")
        
# Try to initialize app, but don't crash if database isn't set up
try:
    initialize_app()
except Exception as e:
    logging.error(f"Error initializing application: {e}")

# This allows running the app with gunicorn
if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
