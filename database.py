import asyncio
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, USE_SUPABASE
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.client: Client = None
        self._connect()

    def _connect(self):
        if USE_SUPABASE:
            try:
                self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("Supabase client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase: {e}")
                self.client = None

    async def _run_async(self, func, *args, **kwargs):
        """Executa uma função síncrona em uma thread separada."""
        if not self.client:
            logger.warning("Supabase client not available.")
            return None
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def check_health(self) -> bool:
        if not self.client:
            return False
        try:
            # Query leve para testar conexão
            res = await self._run_async(
                lambda: self.client.table("instalacoes").select("count", count="exact").limit(1).execute()
            )
            return bool(res)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def get_user(self, user_id: str):
        if not self.client: return None
        try:
            res = await self._run_async(
                lambda: self.client.table("usuarios").select("*").eq("id", str(user_id)).execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None

    async def save_user(self, user_data: dict):
        if not self.client: return False
        try:
            # Converter ID para string se necessário, mas manter consistência
            if 'id' in user_data:
                user_data['id'] = str(user_data['id'])
                
            await self._run_async(
                lambda: self.client.table("usuarios").upsert(user_data).execute()
            )
            return True
        except Exception as e:
            logger.error(f"Error saving user: {e}")
            return False

    async def get_all_users(self):
        if not self.client: return {}
        try:
            # CUIDADO: Se tiver muitos usuários, precisa paginar. 
            # Para < 1000 usuários ok carregar tudo.
            res = await self._run_async(
                lambda: self.client.table("usuarios").select("*").execute()
            )
            users = {}
            for r in (res.data or []):
                users[str(r.get('id'))] = r
            return users
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return {}

    async def save_installation(self, data: dict) -> bool:
        if not self.client: return False
        try:
            await self._run_async(
                lambda: self.client.table("instalacoes").insert(data).execute()
            )
            return True
        except Exception as e:
            logger.error(f"Error saving installation: {e}")
            return False

    async def get_installations(self, filters: dict = None, limit=1000):
        """
        Busca instalações com filtros opcionais.
        Filtros suportados: tecnico_id, data_inicio, data_fim, termo_busca
        """
        if not self.client: return []
        
        def query():
            q = self.client.table("instalacoes").select("*")
            
            if filters:
                if 'tecnico_id' in filters:
                    q = q.eq('tecnico_id', filters['tecnico_id'])
                
                # Filtro de data (assumindo formato DD/MM/YYYY HH:MM no banco, que é string)
                # O ideal seria ter uma coluna timestamp real no banco.
                # Como é string, filtro de range pode falhar se não for ISO.
                # Vou carregar e filtrar no Python se não for possível mudar o banco agora.
                # Pelo código original, é string '%d/%m/%Y %H:%M'. Isso não ordena corretamente.
                # TODO: Migrar coluna data para timestamp no futuro.
                # Por enquanto, mantemos a busca e filtramos no Python para datas, 
                # mas aplicamos outros filtros no banco.
                
                if 'sa' in filters:
                    q = q.eq('sa', filters['sa'])
                
            # Ordenar por inserção (se tiver id autoincrement) ou trazer tudo
            # Como não sei se tem ID sequencial, vou limitar
            return q.limit(limit).execute()

        try:
            res = await self._run_async(query)
            data = res.data or []
            
            # Filtragem de data no Python (infelizmente necessário devido ao formato string BR)
            if filters and ('data_inicio' in filters or 'data_fim' in filters):
                from datetime import datetime
                from config import TZ
                
                filtered_data = []
                inicio = filters.get('data_inicio')
                fim = filters.get('data_fim')
                
                for item in data:
                    try:
                        dt = datetime.strptime(item['data'], '%d/%m/%Y %H:%M').replace(tzinfo=TZ)
                        if inicio and dt < inicio: continue
                        if fim and dt > fim: continue
                        filtered_data.append(item)
                    except:
                        continue
                return filtered_data
            
            # Filtro de busca textual (SA/GPON)
            if filters and 'termo_busca' in filters:
                termo = filters['termo_busca'].lower()
                return [
                    i for i in data 
                    if termo in str(i.get('sa', '')).lower() or termo in str(i.get('gpon', '')).lower()
                ]

            return data
        except Exception as e:
            logger.error(f"Error getting installations: {e}")
            return []

# Instância global
db = DatabaseManager()
