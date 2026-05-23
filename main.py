from sqlalchemy.engine.interfaces import ReflectedColumn

from compare import get_diff_column_attrs, get_diff_columns, get_diff_tables
from compare_database import compare_databases
from config import settings
from db import create_db_engine
from introspection import get_tables, get_columns, get_primary_keys, get_foreign_keys

def main():

    source_db = create_db_engine(settings.source_database_url)
    target_db = create_db_engine(settings.target_database_url)

    changes = compare_databases(source_db, target_db)

    print(changes)
    
if __name__ == "__main__":
    main()
