# 🔧 Guia de Troubleshooting - Bot Técnico

## 🎯 Problemas Comuns e Soluções

### 1. Bot não responde a comandos

#### Sintomas:
- Bot não responde ao `/start`
- Botões não funcionam
- Mensagens não são processadas

#### Possíveis Causas e Soluções:

**A. Bot não está rodando**
```bash
# Verificar se o processo está ativo no Render
# Ou executar localmente:
python start.py
```

**B. Erro de conexão com Telegram**
- Verificar se o `TELEGRAM_TOKEN` está correto no `.env`
- Verificar se não há outra instância do bot rodando
- Logs devem mostrar: `Conflict` ou `NetworkError`

**C. Erro de banco de dados**
- Verificar `SUPABASE_URL` e `SUPABASE_KEY` no `.env`
- Testar conexão: logs devem mostrar "✅ Conexão com Supabase OK!"
- Se mostrar "❌ Falha na conexão com Supabase!", verificar credenciais

**D. Usuário bloqueado ou pendente**
- Verificar status do usuário no banco
- Admin pode aprovar via `/admin`

---

### 2. Fluxo de registro não funciona

#### Sintomas:
- Clica em "Nova Instalação" mas nada acontece
- Bot não pede SA após clicar no botão
- Fluxo para no meio

#### Diagnóstico:

**Verificar logs** (procurar por):
```
✅ Usuário XXXXX iniciou INSTALAÇÃO - modo_registro definido
Estado mudou para AGUARDANDO_SA
```

**Se não aparecer**:
- Problema no `button_callback`
- Verificar se há erro de banco de dados
- Verificar se usuário está bloqueado

**Se aparecer mas não continuar**:
- Problema no `ConversationHandler`
- Verificar se o estado está correto
- Verificar se há conflito de handlers

#### Solução:
```python
# Adicionar mais logs em handlers.py
logger.info(f"Estado atual: {context.user_data}")
```

---

### 3. Máscaras não são geradas

#### Sintomas:
- Clica em "Máscaras" mas não funciona
- Fotos não são processadas
- Máscara não é exibida

#### Possíveis Causas:

**A. Groq API não configurada**
- Verificar `GROQ_API_KEY` no `.env`
- Logs devem mostrar: "⚠️ Groq API não configurada!"

**B. Erro no OCR**
- Verificar se as fotos estão sendo baixadas corretamente
- Verificar logs de erro no `extrair_dados_completos`

**C. Fluxo de máscara quebrado**
- Verificar se o `ConversationHandler` está no estado correto
- Logs devem mostrar transições de estado

---

### 4. Relatórios não aparecem

#### Sintomas:
- Clica em "Relatórios" mas não mostra dados
- Mensagem "Nenhuma instalação encontrada"

#### Possíveis Causas:

**A. Sem dados no banco**
- Verificar se há instalações registradas
- Testar com: `/producao`

**B. Filtro de data incorreto**
- Verificar função `ciclo_atual()` em `utils.py`
- Logs devem mostrar o período sendo consultado

**C. Erro ao buscar dados**
- Verificar conexão com Supabase
- Verificar logs de erro no `db.get_installations()`

---

### 5. Fotos não são salvas

#### Sintomas:
- Envia fotos mas não são registradas
- Erro ao finalizar instalação

#### Possíveis Causas:

**A. Erro ao baixar foto**
- Verificar logs: "Erro ao baixar foto"
- Problema com API do Telegram

**B. Erro ao fazer upload**
- Verificar se Supabase Storage está configurado
- Verificar permissões do bucket

**C. Limite de tamanho**
- Fotos muito grandes podem falhar
- Telegram tem limite de 20MB

---

## 🔍 Como Investigar Problemas

### 1. Ativar Logs Detalhados

No arquivo `tecnico_bot.py`, mudar:
```python
logger.setLevel(logging.DEBUG)  # Em vez de INFO
```

### 2. Verificar Estado do ConversationHandler

Adicionar em qualquer handler:
```python
logger.info(f"Estado atual: {context.user_data}")
logger.info(f"Conversation state: {context._conversation_states}")
```

### 3. Testar Conexões

**Supabase**:
```python
# Em database.py
health = await db.check_health()
print(f"Supabase: {'OK' if health else 'ERRO'}")
```

**Telegram**:
```python
# Em tecnico_bot.py
me = await app.bot.get_me()
print(f"Bot: {me.username}")
```

### 4. Verificar Variáveis de Ambiente

Criar arquivo `test_env.py`:
```python
import os
from dotenv import load_dotenv
load_dotenv()

print("TELEGRAM_TOKEN:", "✅" if os.getenv("TELEGRAM_TOKEN") else "❌")
print("SUPABASE_URL:", "✅" if os.getenv("SUPABASE_URL") else "❌")
print("SUPABASE_KEY:", "✅" if os.getenv("SUPABASE_KEY") else "❌")
print("GROQ_API_KEY:", "✅" if os.getenv("GROQ_API_KEY") else "❌")
print("ADMIN_IDS:", os.getenv("ADMIN_IDS"))
```

---

## 📊 Checklist de Diagnóstico

Quando o bot não funcionar, verificar na ordem:

- [ ] 1. Bot está rodando? (processo ativo)
- [ ] 2. Logs mostram "BOT INICIADO COM SUCESSO"?
- [ ] 3. Conexão com Supabase OK?
- [ ] 4. Token do Telegram válido?
- [ ] 5. Variáveis de ambiente carregadas?
- [ ] 6. Usuário tem permissão? (não bloqueado/pendente)
- [ ] 7. ConversationHandler está funcionando?
- [ ] 8. Handlers estão registrados corretamente?

---

## 🚨 Erros Críticos

### "Conflict: terminated by other getUpdates request"
**Causa**: Outra instância do bot está rodando
**Solução**: Parar todas as instâncias e reiniciar apenas uma

### "Unauthorized"
**Causa**: Token do Telegram inválido
**Solução**: Verificar `TELEGRAM_TOKEN` no `.env`

### "Connection refused"
**Causa**: Supabase não acessível
**Solução**: Verificar URL e chave, verificar se projeto está ativo

### "ConversationHandler timeout"
**Causa**: Estado do conversation não está sendo mantido
**Solução**: Verificar `per_user=True` e `per_chat=True` no ConversationHandler

---

## 📞 Comandos de Debug

### No Telegram:
- `/start` - Reiniciar bot
- `/meuid` - Ver seu ID
- `/cancelar` - Limpar estado
- `/admin` - Painel admin (verificar usuários)

### No Terminal:
```bash
# Ver logs em tempo real (Render)
render logs -t

# Testar localmente
python start.py

# Verificar sintaxe
python check_syntax.py

# Testar variáveis de ambiente
python test_env.py
```

---

## 💡 Dicas

1. **Sempre verificar os logs primeiro**
2. **Testar uma funcionalidade por vez**
3. **Usar `/cancelar` entre testes**
4. **Verificar se o banco tem dados**
5. **Testar com usuário admin primeiro**

---

**Última atualização**: 2026-02-04
