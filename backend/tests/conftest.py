"""All integration tests must use an explicitly selected disposable database."""
import os

engine = os.environ.get('TEST_DB_ENGINE')
database = os.environ.get('TEST_MYSQL_DATABASE', '')
if engine != 'mysql' or not database.startswith('test_'):
    raise RuntimeError('Tests require TEST_DB_ENGINE=mysql and TEST_MYSQL_DATABASE starting with test_')
os.environ['APP_DB_ENGINE'] = 'mysql'
os.environ['MYSQL_DATABASE'] = database
