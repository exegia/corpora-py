from supabase import Client, create_client

from shared.utils.constant import SUPABASE_API_URL, SUPABASE_SECRET_KEY

url: str = SUPABASE_API_URL
key: str = SUPABASE_SECRET_KEY
supabase: Client = create_client(url, key)
