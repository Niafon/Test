from sqlalchemy.engine.interfaces import ReflectedColumn

from compare import get_diff_tables
from config import settings
from db import create_db_engine
from introspection import get_tables, get_columns, get_primary_keys, get_foreign_keys

def main():

    source_db = create_db_engine(settings.source_database_url)
    target_db = create_db_engine(settings.target_database_url)

    source_tables = get_tables(source_db)
    target_tables = get_tables(target_db)
    print("Source Database Tables:")
    for table in source_tables:
        print(f"- {table}")
    print("\nTarget Database Tables:")
    for table in target_tables:
        print(f"- {table}")

    diff_tables, common_tables = get_diff_tables(source_tables, target_tables)
    print(f"\nDiff: {diff_tables}")
    print(f"Common Tables: {common_tables}")


"""     for name in source_tables:
        source_columns: list[ReflectedColumn] = get_columns(source_db, name)
        source_pk = get_primary_keys(source_db, name)
        source_fks = get_foreign_keys(source_db, name)
        print(f"TABLE: {name} - Source Database pk: {source_pk['constrained_columns']}, {source_pk['name']}")
        print(f"TABLE: {name} - Source Database fks: {source_fks}")
        print(f"TABLE: {name} - Source Database columns:")
        for columns in source_columns:
            print(f"- {columns['name']} ({columns['type']})")
    for name in target_tables:
        target_columns: list[ReflectedColumn] = get_columns(target_db, name)
        target_pk = get_primary_keys(target_db, name)
        target_fks = get_foreign_keys(target_db, name)
        print(f"TABLE: {name} - Target Database pk: {target_pk['constrained_columns']}, {target_pk['name']}")
        print(f"TABLE: {name} - Target Database fks: {target_fks}")
        print(f"TABLE: {name} - Target Database columns:")
        for columns in target_columns:
            print(f"- {columns['name']} ({columns['type']})") """




if __name__ == "__main__":
    main()
