"""Create only the configured application database before starting the API."""
import re

from .config import get_settings


def main():
    settings = get_settings()
    if settings.app_db_engine != 'mysql':
        print('SQLite selected; no server database creation required.')
        return
    import pymysql

    database = settings.mysql_database
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', database):
        raise ValueError('MYSQL_DATABASE must contain only letters, digits or underscores')
    connection = pymysql.connect(
        host=settings.mysql_host, port=settings.mysql_port,
        user=settings.mysql_user, password=settings.mysql_password,
        connect_timeout=settings.mysql_connect_timeout, charset='utf8mb4',
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE DATABASE IF NOT EXISTS `{database}` '
                'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
            )
        connection.commit()
        print(f'Application database ready: {database}')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
