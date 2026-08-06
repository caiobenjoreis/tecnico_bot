import asyncio
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, USE_SUPABASE
from cachetools import TTLCache
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.client: Client = None
        self._user_cache = TTLCache(maxsize=500, ttl=300)  # Cache 5 min
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

    async def get_user(self, user_id: str, use_cache: bool = True):
        """Busca usuário com cache opcional (TTL 5 min)."""
        if not self.client: return None
        
        user_id_str = str(user_id)
        
        # Verificar cache primeiro
        if use_cache and user_id_str in self._user_cache:
            return self._user_cache[user_id_str]
        
        try:
            res = await self._run_async(
                lambda: self.client.table("usuarios").select("*").eq("id", user_id_str).execute()
            )
            if res.data:
                user = res.data[0]
                # Armazenar no cache
                self._user_cache[user_id_str] = user
                return user
            return None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None

    async def update_user_status(self, user_id: str, status: str) -> bool:
        """Atualiza o status de um usuário (ex: 'ativo', 'bloqueado')."""
        if not self.client: return False
        try:
            await self._run_async(
                lambda: self.client.table("usuarios").update({"status": status}).eq("id", str(user_id)).execute()
            )
            # Invalidar cache do usuário
            self._user_cache.pop(str(user_id), None)
            return True
        except Exception as e:
            logger.error(f"Error updating user status {user_id}: {e}")
            return False

    async def save_user(self, user_data: dict):
        if not self.client: return False
        try:
            # Converter ID para string se necessário, mas manter consistência
            if 'id' in user_data:
                user_data['id'] = str(user_data['id'])
                # Invalidar cache
                self._user_cache.pop(user_data['id'], None)
                
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
            res = await self._run_async(
                lambda: self.client.table("usuarios").select("*").execute()
            )
            users = {}
            for r in (res.data or []):
                user_id = str(r.get('id'))
                users[user_id] = r
                # Atualizar cache
                self._user_cache[user_id] = r
            return users
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return {}

    def invalidate_user_cache(self, user_id: str = None):
        """Invalida cache de usuário específico ou todo o cache."""
        if user_id:
            self._user_cache.pop(str(user_id), None)
        else:
            self._user_cache.clear()

    async def check_sa_exists(self, sa: str) -> bool:
        """Verifica se uma SA já foi registrada (normalizes SA first)."""
        if not self.client: return False
        # Normalize SA before checking
        sa_normalized = str(sa).strip().upper()
        if sa_normalized.isdigit():
            sa_normalized = f"SA-{sa_normalized}"
        try:
            res = await self._run_async(
                lambda: self.client.table("instalacoes").select("id").eq("sa", sa_normalized).limit(1).execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.error(f"Error checking SA {sa}: {e}")
            return False

    async def save_installation(self, data: dict) -> bool:
        if not self.client: return False
        try:
            # Normalize SA before saving
            if 'sa' in data:
                sa_normalized = str(data['sa']).strip().upper()
                if sa_normalized.isdigit():
                    sa_normalized = f"SA-{sa_normalized}"
                data['sa'] = sa_normalized
            
            await self._run_async(
                lambda: self.client.table("instalacoes").insert(data).execute()
            )
            return True
        except Exception as e:
            logger.error(f"Error saving installation: {e}")
            return False

    async def get_installations(self, filters: dict = None, limit=5000):
        """
        Busca instalações com filtros opcionais.
        Filtros suportados: tecnico_id, data_inicio, data_fim, termo_busca, sa
        
        Datas podem ser objetos datetime. Novos registros são armazenados em ISO,
        registros legados em formato BR (dd/mm/YYYY HH:MM) são filtrados no Python.
        """
        if not self.client: return []
        
        def query():
            q = self.client.table("instalacoes").select("*")
            
            if filters:
                if 'tecnico_id' in filters:
                    q = q.eq('tecnico_id', filters['tecnico_id'])
                
                if 'sa' in filters:
                    # Normalize SA filter
                    sa_filter = str(filters['sa']).strip().upper()
                    if sa_filter.isdigit():
                        sa_filter = f"SA-{sa_filter}"
                    q = q.eq('sa', sa_filter)

                # Busca textual via ilike no banco (evita carregar tudo em memória)
                if 'termo_busca' in filters:
                    termo = filters['termo_busca']
                    q = q.or_(
                        f"sa.ilike.%{termo}%,gpon.ilike.%{termo}%,serial_modem.ilike.%{termo}%"
                    )

                # Filtro de data: aplica no banco apenas para registros ISO (YYYY-MM-DD...)
                # Registros legados (dd/mm/YYYY) serão filtrados no Python abaixo
                if 'data_inicio' in filters and filters['data_inicio']:
                    q = q.gte('data', filters['data_inicio'].isoformat())
                if 'data_fim' in filters and filters['data_fim']:
                    q = q.lte('data', filters['data_fim'].isoformat())

            q = q.order('id', desc=True)
            return q.limit(limit).execute()

        try:
            res = await self._run_async(query)
            data = res.data or []

            # Filtro Python de fallback para registros legados (formato BR dd/mm/YYYY HH:MM)
            # e para garantir que registros ISO fora do range não vazem
            if filters and ('data_inicio' in filters or 'data_fim' in filters):
                from utils import parse_data
                inicio = filters.get('data_inicio')
                fim = filters.get('data_fim')
                filtered_data = []
                for item in data:
                    dt = parse_data(item.get('data', ''))
                    if dt is None:
                        continue
                    if inicio and dt < inicio:
                        continue
                    if fim and dt > fim:
                        continue
                    filtered_data.append(item)
                return filtered_data

            return data
        except Exception as e:
            logger.error(f"Error getting installations: {e}")
            return []

# Instância global
db = DatabaseManager()
