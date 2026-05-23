


def get_diff_tables(source_table: list[str], target_table: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    source_tables = set(source_table)
    target_tables = set(target_table)

    diff_tables = []
    common_tables = []
    for x in source_tables:
        if x not in target_tables:
            diff_tables.append(
                {
                    "kind": "missing_table",
                    "table": x,
                }
            )
    for x in target_tables:
        if x not in source_tables:
            diff_tables.append(
                {
                    "kind": "extra_table",
                    "table": x,
                }
            )
    for x in source_tables:
        if x in target_tables:
            common_tables.append(x)
    return diff_tables, common_tables

def get_diff_columns(source_columns: list[str], target_columns: list[str]):
    source_columns_set = set(source_columns)
    target_columns_set = set(target_columns)

    diff_columns = []
    common_columns = []
    for x in source_columns_set:
        if x not in target_columns_set:
            diff_columns.append(
                {
                    "kind": "missing_column",
                    "column": x,
                }
            )
    for x in target_columns_set:
        if x not in source_columns_set:
            diff_columns.append(
                {
                    "kind": "extra_column",
                    "column": x,
                }
            )
    for x in source_columns_set:
        if x in target_columns_set:
            common_columns.append(x)
    return diff_columns, common_columns
