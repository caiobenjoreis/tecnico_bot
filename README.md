# Bot Técnico — Registro, Produção e Relatórios

O Bot Técnico automatiza o registro de serviços (instalações e reparos), consulta de produção com regras de bonificação, e geração de relatórios operacionais diretamente pelo Telegram. Os dados são persistidos no Supabase.

## Visão Geral

- Interface via Telegram com teclado inline e comandos.
- Persistência no Supabase (`instalacoes`, `usuarios`).
- Consulta de produção com ciclo 16→15, Modo Turbo, faixas e valores por ponto.
- Relatórios: mensal, semanal, período, hoje e ranking.
- Fluxos separados para instalação e reparo, com seleção de tipo de atividade.

## Funcionalidades

- Registrar Instalação
  - Coleta SA, GPON, tipo da atividade (ex.: Instalação, Instalação TV), 3 fotos e opcionalmente serial do modem.
  - Salva com identificação do técnico (id, nome, região) e data de execução.
- Registrar Reparo
  - Coleta SA/OS, GPON, tipo do reparo (ex.: Defeito Banda Larga, Defeito Linha, Defeito TV, Mudança de Endereço, Retirada, Serviços), e fotos.
  - Salva com os mesmos metadados da instalação e classifica como `categoria=reparo`.
- Consultar SA/GPON
  - Busca por SA ou GPON e retorna os dados e fotos associadas.
- Minhas Instalações
  - Lista as últimas instalações/reparos do técnico autenticado.
- Relatórios Operacionais
  - Mensal, semanal, por período, hoje e ranking geral de técnicos.
- Consulta Produção (Modelo Vtal)
  - Ciclo automático 16 do mês corrente → 15 do mês seguinte.
  - Cálculo de pontos por atividade com pesos específicos.
  - Modo Turbo ativo com ≥24 dias produtivos (dias com pelo menos 1 serviço concluído).
  - Determinação da faixa A–I e valores por ponto (normal e Turbo), com exibição de mínimos da faixa.

## Fluxos de Uso

- Menu Inicial
  - 📝 Registrar Instalação
  - 🔧 Registrar Reparo
  - 🔍 Consultar SA/GPON
  - 📊 Minhas Instalações
  - 📆 Consulta Produção
  - 📈 Relatórios
- Instalação
  1. Informar SA → GPON → escolher tipo → enviar 3 fotos → `/finalizar`.
- Reparo
  1. Informar SA/OS → GPON → escolher tipo de reparo → enviar 3 fotos → `/finalizar`.

## Regras de Produção e Bonificação (Vtal)

- Pesos por atividade (pontos por serviço):
  - `defeito_banda_larga`: 1,43
  - `defeito_linha`: 1,43
  - `defeito_tv`: 1,43
  - `instalacao`: 2,28
  - `instalacao_tv`: 3,58
  - `mudanca_endereco`: 2,37
  - `retirada`: 1,06
  - `servicos`: 1,50
- Modo Turbo
  - Ativado com ≥24 dias produtivos no ciclo 16→15.
- Faixas e valores
  - A ≥164: R$ 3,20 | Turbo R$ 8,00
  - B 159–163,99: R$ 2,40 | Turbo R$ 6,00
  - C 148–158,99: R$ 1,60 | Turbo R$ 4,00
  - D 137–147,99: R$ 1,00 | Turbo R$ 2,50
  - E 126–136,99: R$ 0,80 | Turbo R$ 2,25
  - F 120–125,99: R$ 0,70 | Turbo R$ 2,00
  - G 115–119,99: R$ 0,70 | Turbo R$ 1,75
  - H 109–114,99: R$ 0,60 | Turbo R$ 1,50
  - I 0–108,99: R$ 0,00 | Turbo R$ 0,00
- Relatório de produção exibe:
  - Total de serviços, pontos, faixa, dias produtivos, status do Turbo, valor por ponto, valor total, mínimos da faixa (c/ e s/ Turbo) e média diária.

## Comandos do Bot

- `/start` — Abre o menu principal.
- `/ajuda` — Lista de comandos e dicas.
- `/cancelar` — Cancela a operação corrente.
- `/meuid` — Exibe seu ID do Telegram.
- `/mensal` — Relatório mensal.
- `/semanal` — Relatório semanal.
- `/hoje` — Relatório do dia.
- `/consultar` — Prompt para buscar por SA/GPON.
- `/reparo` — Inicia registro de reparo diretamente.
- `/producao` — Consulta produção do ciclo atual 16→15.

## Integrações

- Supabase
  - Persistência nas tabelas `instalacoes` e `usuarios`.
  - Usa `SUPABASE_URL` e `SUPABASE_KEY` (Service Role recomendado para escrita com RLS).
- Telegram
  - Validação do token e operação via webhook (se `WEBHOOK_BASE_URL`/`RENDER_EXTERNAL_URL`) ou polling.

## Configuração

- Variáveis de Ambiente
  - `TELEGRAM_TOKEN` — Token do bot do Telegram.
  - `SUPABASE_URL` — URL do projeto Supabase.
  - `SUPABASE_KEY` — Service Role Key ou chave com permissões de escrita.
  - `WEBHOOK_BASE_URL` ou `RENDER_EXTERNAL_URL` — Base URL pública para webhook (ex.: Render).
  - `PORT` — Porta do servidor (default `10000`).
- Execução
  - Webhook: inicia um servidor HTTP e registra webhook em `BASE_URL/<TOKEN>`.
  - Polling: quando não há `BASE_URL`, roda em modo polling.

## Estrutura de Dados (Supabase)

- Tabela `instalacoes`
  - `id` bigint identity primary key
  - `sa` text not null
  - `gpon` text not null
  - `tipo` text not null
  - `categoria` text not null (`instalacao` ou `reparo`)
  - `fotos` text[] not null default `{}`
  - `tecnico_id` bigint not null
  - `tecnico_nome` text
  - `tecnico_regiao` text
  - `serial_modem` text (opcional)
  - `data` text not null (`dd/MM/YYYY HH:MM`)
  - `created_at` timestamptz default `now()`
- Tabela `usuarios`
  - `id` bigint primary key
  - `nome` text
  - `sobrenome` text
  - `regiao` text
  - `telegram` text

## Relatórios

- Mensal: total e quebra por técnico, média diária até o dia atual.
- Semanal: período da semana corrente, total e quebra por técnico, média diária.
- Dia: total e quebra por técnico.
- Período: SA/GPON das últimas 10 entradas no intervalo.
- Ranking: ordenado por total geral de serviços.

## Boas Práticas e Segurança

- Nunca exponha `TELEGRAM_TOKEN` ou chaves do Supabase em código/logs públicos.
- Com RLS ativo, use `SUPABASE_KEY` de Service Role para operações do bot ou crie Policies específicas.
- Valide entradas e trate erros de escrita (o bot já informa falhas de persistência no Supabase).

## Troubleshooting

- Registros não aparecem no Supabase
  - Verifique se o schema tem as colunas esperadas e se `tipo`/`categoria`/`data` não estão `NULL` quando há `NOT NULL` aplicado.
  - Em RLS, confirme que a chave é `Service Role` ou que as Policies permitem escrita.
- Bot não inicia
  - Cheque `TELEGRAM_TOKEN` válido, `SUPABASE_URL`/`SUPABASE_KEY` definidos e logs do serviço.
- Webhook não recebe mensagens
  - Confirme `WEBHOOK_BASE_URL`/`RENDER_EXTERNAL_URL` e que o endpoint público está acessível.

## Personalizações

- Adicionar novos tipos de serviço: incluir o tipo no teclado e no mapa de pesos.
- Ajustar pesos/faixas/valores: editar a tabela de constantes da produção.
- Mudar armazenamento da data para `timestamptz`: adaptar inserção e parsing nos relatórios.

