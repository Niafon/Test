from compare import get_diff_column_attrs, get_diff_columns, get_diff_tables
from introspection import get_columns, get_tables



def compare_databases(source_db, target_db):
    changes = []

    source_tables = get_tables(source_db)
    target_tables = get_tables(target_db)

    diff_tables, common_tables_details = get_diff_tables(source_tables, target_tables)
    changes.extend(diff_tables)
    
    for table in common_tables_details:
        source_columns = get_columns(source_db, table)
        target_columns = get_columns(target_db, table)

        diff_columns, common_column_details = get_diff_columns(table, source_columns, target_columns)

        changes.extend(diff_columns)

        column_attr_diffs = get_diff_column_attrs(common_column_details)

        changes.extend(column_attr_diffs)

    return changes
