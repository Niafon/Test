from sqlalchemy import Engine, create_engine

# Сзодания подкючения к бд
def create_db_engine(db_url: str) -> Engine:
    return create_engine(db_url)
