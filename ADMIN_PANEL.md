# 🎛️ Painel de Administração - Bot Técnico

## Como configurar administradores

### 1. Descobrir seu ID do Telegram

**Método 1 - Comando `/meuid` (MAIS FÁCIL):**
1. Envie `/meuid` para o bot
2. O bot responderá com seu ID, nome e username
3. Copie o número do ID

**Método 2 - Logs do Render:**
1. Faça deploy do bot
2. Envie `/start` para o bot
3. Vá nos **Logs do Render** (https://dashboard.render.com)
4. Procure por uma linha como: `🔍 User ID: 123456789 | Username: seu_nome`
5. Copie o número do ID

### 2. Adicionar como administrador

1. Abra o arquivo `tecnico_bot`
2. Encontre a seção `ADMIN_IDS` (linha ~23)
3. Adicione seu ID:

```python
ADMIN_IDS = [
    123456789,  # Seu ID aqui
    987654321,  # Outro admin (opcional)
]
```

4. Faça commit e push (ou upload manual no GitHub)
5. O Render fará deploy automaticamente

## Comandos do Painel Admin

### `/meuid` - Descobrir seu ID
- Mostra seu ID do Telegram
- Mostra seu nome e username
- Instruções para se tornar admin

### `/admin` - Abre o painel principal

Funcionalidades disponíveis:

#### 📊 Estatísticas Gerais
- Total de técnicos cadastrados
- Total de instalações
- Instalações nos últimos 7 dias
- Distribuição por tipo de serviço
- Top 5 técnicos

#### 👥 Listar Técnicos
- Lista completa de todos os técnicos
- Mostra ID, nome, região
- Quantidade de instalações por técnico
- Indica quem é admin (👑)

#### 📋 Todas Instalações
- Últimas 20 instalações do sistema
- Mostra SA, GPON, técnico, tipo e data
- Ordenadas da mais recente para a mais antiga

#### 📢 Enviar Mensagem para Todos **[NOVO]**
- Envia avisos e comunicados para todos os técnicos
- Suporta formatação Markdown
- Relatório de envio com estatísticas
- Mostra quantas mensagens foram enviadas com sucesso

**Como usar:**
1. Clique em "📢 Enviar Mensagem para Todos"
2. Digite sua mensagem (pode usar Markdown para formatação)
3. A mensagem será enviada automaticamente para todos
4. Você receberá um relatório com:
   - ✅ Mensagens enviadas com sucesso
   - ❌ Falhas (usuários que bloquearam o bot)
   - 👥 Total de técnicos

**Exemplo de mensagem:**
```
🔔 *Atenção Técnicos!*

Amanhã teremos manutenção no sistema das 8h às 10h.

Por favor, registrem suas instalações antes ou depois desse horário.

Obrigado!
```

#### 📤 Exportar Dados
- Informações sobre como exportar dados
- Link direto para o Supabase Dashboard
- Comandos úteis para relatórios

#### 🔧 Gerenciar Admins
- Instruções para adicionar/remover admins
- Como descobrir IDs de usuários

## Segurança

- ✅ Apenas usuários na lista `ADMIN_IDS` têm acesso
- ✅ Tentativas de acesso não autorizado são bloqueadas
- ✅ Todos os acessos são logados no Render
- ✅ Broadcast só pode ser enviado por admins

## Dicas

1. **Mantenha a lista de admins atualizada** - Remova IDs de pessoas que não precisam mais de acesso
2. **Use o Supabase para análises avançadas** - O painel é para visualização rápida
3. **Verifique os logs regularmente** - Para monitorar atividades suspeitas
4. **Use Markdown no broadcast** - Para mensagens mais bonitas e organizadas
5. **Teste o broadcast primeiro** - Envie para você mesmo antes de enviar para todos

## Exemplo de uso

### Descobrir ID:
1. Envie `/meuid` para o bot
2. Copie o ID que aparece
3. Envie para o administrador

### Acessar painel:
1. Envie `/admin` para o bot
2. Clique em "📊 Estatísticas Gerais"
3. Veja o resumo completo do sistema
4. Use "🔙 Voltar" para retornar ao menu

### Enviar broadcast:
1. Envie `/admin`
2. Clique em "📢 Enviar Mensagem para Todos"
3. Digite sua mensagem
4. Aguarde o relatório de envio

## Troubleshooting

**Problema:** Comando `/admin` não aparece
- **Solução:** Verifique se seu ID está na lista `ADMIN_IDS`

**Problema:** "Acesso negado"
- **Solução:** Confirme que adicionou o ID correto (números apenas, sem aspas)

**Problema:** Não consigo ver meu ID
- **Solução:** Use o comando `/meuid` - é mais fácil!

**Problema:** Broadcast não enviou para todos
- **Solução:** Alguns usuários podem ter bloqueado o bot. Verifique o relatório de envio.

**Problema:** Erro ao enviar broadcast
- **Solução:** Verifique se a mensagem não tem caracteres especiais que quebram o Markdown
