# Registro de decisões e validação

Aplicação: notebook Colab de assistente de voz. Integração original: `openai.ChatCompletion.create`, removida do SDK atual. Integração aprovada: `OpenAI().chat.completions.create`, modelo `gpt-6-luna`, uma mensagem de usuário e texto completo para gTTS.

## Aprovação e etapas

O autor respondeu **“aprovado”** ao conjunto de correções apresentado na conversa: cliente OpenAI atual, chave segura, captura e liberação do microfone, formatos reais, validação de sequência/conteúdo/dependências/FFmpeg e limpeza de saídas. Autorizou implementar e testar **sem consumir a API**. Fluxo: entregar o conjunto aprovado; solicitar nova decisão somente se o escopo precisar mudar.

1. **Atual: corrigir o fluxo existente e validar localmente — aprovado.** Notebook independente para Colab, README atualizado, testes sem rede externa e captura em navegador com dispositivo simulado. Dependências: Python, Node.js, SDK e bibliotecas de teste. Implementação e testes locais concluídos.
2. **Validação real — pendente de recursos e decisão de credenciais.** Microfone físico, Colab, download/inferência Whisper, OpenAI e gTTS reais não serão simulados como validação concluída.
3. **Opcional, não aprovado:** Responses API com eventual modelo novo, streaming, histórico, ferramentas, interface web ou execução local da aplicação.

## Ajuste de modelo e diagnóstico: aprovação recebida

O autor relatou `HTTP 404 / model_not_found / invalid_request_error` no Colab ao usar `gpt-4`. A resposta **“sim”** aprovou atualizar para `gpt-6-luna`, priorizar rapidez e melhorar mensagens com HTTP/código, além de atualizar testes/README/PR sem fazer chamadas pagas. Modelo atual: `gpt-6-luna`, `reasoning_effort="none"`, endpoint Chat Completions. É um ajuste aprovado do fluxo existente; Responses/histórico/ferramentas permanecem fora do escopo.

Fonte oficial consultada: https://developers.openai.com/api/docs/models/gpt-6-luna — confirma Chat Completions e esforço `none`. Sem novo cache, estado, tiers, limite de tokens, verbosidade ou instruções de sistema. Esforço aplicado apenas ao identificador aprovado; overrides de outros modelos não recebem parâmetros não verificados. Acesso da conta, qualidade, custo observado e latência real continuam desconhecidos até novo teste no Colab.

Validação adicional: modelo/perfil no JSON da requisição do SDK real, overrides de modelo sem `reasoning_effort`, diagnóstico 404, códigos HTTP e conhecidos preservados, mensagens/códigos arbitrários sem exposição de dados, cota distinguida de rate limit e fechamento do cliente nas falhas. Todos executados em transporte simulado, sem requisição paga.

## Cobertura das decisões da avaliação

A avaliação de cada seção está em `docs/revisao-tecnica.md`, tabela “Avaliação da integração OpenAI”. Esta implementação aplica somente os itens autorizados e preserva os demais:

| Item | Aplicável / suporte | Decisão e evidência |
| --- | --- | --- |
| Modelo | Sim / SDK e documentação suportam `gpt-6-luna`; acesso real desconhecido | Troca aprovada após `gpt-4` retornar 404 / `model_not_found` na conta do autor. |
| Arquivos de instrução | Não / não há arquivo existente | Não adicionar AGENTS.md. |
| Responses | Opcional / modelo e controles precisariam de decisão | Fora do escopo aprovado; modernizar a interface Chat Completions é suficiente para a falha. |
| Streaming | Não ao reparo / SDK suporta | Preservar resposta completa para síntese. |
| WebSocket | Não / não verificado para modelo atual | Sem sessões persistentes ou ferramentas. |
| Privacidade, retenção e residência | Requisitos especiais desconhecidos | Não adicionar retenção de estado nem afirmar ZDR/residência. Documentar fluxo existente OpenAI/Google/Colab. |
| Processing tiers | Não ao reparo / padrão existente | Não adicionar Priority, Flex, Batch ou Reserved. |
| Cache: chaves, retenção, breakpoints, diagnóstico | Não / prefixo reutilizável ausente | Uma pergunta independente; não introduzir parâmetros. |
| Estado e persistência de instruções | Não / não há histórico nem instrução de sistema | Preservar uma mensagem de usuário; limpar estado local inválido entre tentativas. |
| Raciocínio: criptografia, esforço, preservação, resumos e preâmbulos | Esforço aplicável / `none` suportado em Chat Completions | `reasoning_effort="none"` aprovado para `gpt-6-luna`. Não encaminhar a outros modelos, nem introduzir histórico/resumos. |
| Verbosidade | Não ao reparo / sem preferência existente | Não impor valor. |
| Tokens máximos | Não ao reparo / limite original ausente | Não introduzir limite; rejeitar respostas incompletas em vez de sintetizá-las como completas. |
| Fases de mensagens | Não / sem replay de assistente | Não acrescentar fases. |
| Compactação | Não / sem histórico | Não acrescentar. |
| Saída estruturada | Não / texto livre necessário | Preservar texto livre. |
| Ferramentas: escolha, busca/additional_tools, paralelas, programáticas e interfaces | Não / nenhuma ferramenta ao modelo | Não acrescentar ferramentas nem agentes. |

Fornecedor e framework: SDK oficial OpenAI, sem intermediários. Fonte de compatibilidade: README oficial `openai/openai-python`, consultado na avaliação; Chat Completions continua suportado e a sintaxe moderna é `client.chat.completions.create`. Acesso legado foi reproduzido como `APIRemovedInV1` em OpenAI 2.54.0. Não há headers de outro provedor a traduzir.

## Mapa de implementação e testes

| Caminho | Implementação verificada | Verificação |
| --- | --- | --- |
| Transcrição → OpenAI → texto | Cliente atual/context manager, modelo padrão aprovado `gpt-6-luna`, perfil rápido e mensagem de usuário; validar texto e conclusão | SDK real com `httpx.MockTransport`, verificando URL, payload, retorno, erros, ausência de texto, resposta incompleta e fechamento do cliente. |
| Credencial | Ambiente ou segredo Colab, nunca sobrescrever/exibir | Ambiente, placeholder, segredo, ausência/negação e erros redigidos. |
| Gravação | Rejeitar erros, liberar trilhas, MIME real e conteúdo válido | JavaScript original do notebook em Node com mocks de sucesso/falhas; Chromium com microfone simulado. |
| Etapas locais | Invalidar variáveis dependentes, validar arquivo e conteúdo antes de avançar | Executar células reais com fronteiras externas substituídas; sucesso e falhas/reexecução. |
| Whisper/gTTS | Arquivo e FFmpeg válidos, sem fala vazia; MP3 e escrita atômica | Modelos/serviços substituídos; arquivos reais temporários e falhas de I/O. |
| Notebook/docs | Saídas limpas, esquema/sintaxe/links | nbformat, compilação, links locais, `git diff --check`, `pip check` do ambiente de teste. |

## Resultado

A etapa 1 aprovada foi implementada e validada localmente: **43 testes Python e 13 testes Node aprovados**, além do teste Chromium 156.0.8078.79 (Playwright 1.62.1), com áudio WebM/Opus validado por ffprobe, permissão negada e trilhas encerradas. A suíte completa criada para o projeto passou. `pip check` passou no ambiente virtual de testes; notebook válido, células compiláveis, sem saídas e links internos válidos.

Exemplo do caminho mantido: configurar `OPENAI_API_KEY` no ambiente ou nos Segredos do Colab, transcrever uma pergunta e executar `ask_chatgpt(transcription, model_name="gpt-6-luna")`; a função usa o cliente atual e retorna texto completo. Os testes verificam requisições pelo SDK real com MockTransport, sem rede externa.

Serviços reais e implantação não foram verificados. A etapa 2 depende de Colab, microfone físico, Whisper, chave/acesso/cota OpenAI e Google; não há autorização para consumir API nesta fase. O conflito global de `click` no Colab permanece informado, sem migração de arquitetura. Evoluções da etapa 3 não estão aprovadas. O autor atualizou o acesso do GitHub; a versão segue para revisão por PR na branch `codex/corrige-assistente-voz`. A incorporação na branch principal não faz parte deste envio.

Evidências detalhadas e limites: `docs/revisao-tecnica.md` e `docs/validacao/resultados-corrigido.json`.
