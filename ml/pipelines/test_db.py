import psycopg2
from dotenv import load_dotenv
import os

print("Loading environment variables...")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to SUPABASE...")

try:

    conn = psycopg2.connect(DATABASE_URL)

    print("CONNECTED SUCCESSFULLY!")

    conn.close()

except Exception as e:

    print("ERROR:")
    print(e)