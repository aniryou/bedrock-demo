from mangum import Mangum

from snowflake_stub.app import app

handler = Mangum(app)
