# Piloto 01 — conferência de nomes e versões

Estado: **EM INVESTIGAÇÃO**, aguardando avaliação do operador. Autorização de 27/10/2026 limitada a código, documentação deste piloto e testes sintéticos. Não autoriza uso com acervo real, instalação em produção, merge ou publicação.

Reaproveita `production_engine.py` da base experimental `55d842a`. Não substitui o Media Manager. Usa somente a biblioteca padrão do Python; Python 3.12 recomendado. Não é necessário iniciar Flask, instalar dependências ou abrir o Manager.

## Teste sintético no Windows

Depois de receber e aprovar a revisão desta branch, abra PowerShell na pasta que contém `production_engine.py`. Estes comandos criam uma pasta temporária nova com arquivos **sintéticos vazios**; eles não são imagens ou vídeos reproduzíveis. Não selecione `data`, backups ou pastas reais.

```powershell
$pastaPiloto = Join-Path ([System.IO.Path]::GetTempPath()) ("LEONAN Piloto São Paulo " + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $pastaPiloto | Out-Null
$nomesPiloto = @("EP14_IMG01_V1.png", "EP14_IMG01_V2.png", "EP14_IMG08.png", "EP14_IMG09.png", "EP14_IMG10.png", "EP14_IMG80.png", "EP14_IMG02.png.png", "EP14_IMG03(1).png", "EP14_IMG04_V1_V2.png", "EP15_IMG01_V10.png")
foreach ($nomePiloto in $nomesPiloto) { New-Item -ItemType File -Path (Join-Path $pastaPiloto $nomePiloto) | Out-Null }
py -3 production_engine.py --source "$pastaPiloto" --episode EP14 --expected-takes 7
py -3 production_engine.py --source "$pastaPiloto" --episode EP14 --expected-takes 8 --format json
```

O programa imprime no terminal. Não fornece opção para salvar relatório, não cria arquivos na pasta examinada e não lê conteúdo de mídia. O formato padrão mudou de JSON para texto legível; automações que precisam de JSON devem usar explicitamente `--format json`. Chaves anteriores como `takes` e `unmatched_media` permanecem; novos campos explicam exclusões, outros episódios e entradas ignoradas.

A pasta sintética é independente. Não há comando de limpeza neste roteiro. Parar de executar o utilitário encerra o piloto, sem precisar restaurar o Manager.

## Interpretação

- TAKE 01, 09, 10 e 80 são lidos integralmente. O intervalo esperado aceita 1–8 takes; números fora do intervalo são relatados, nunca remapeados. Sete é o padrão; oito deve corresponder ao planejamento autorizado.
- `.png.png` e combinações como `.jpg.png` são alertadas e excluídas da seleção. Nenhum arquivo é renomeado.
- V1, V2, V10 e V1.4 são versões **escritas no nome**, não aprovadas. Nenhuma preferência automática por versão maior.
- V1_V2, V1.2.3 e sufixos não reconhecidos geram alerta; o relatório não escolhe uma versão. Candidatos com esses avisos ainda exigem conferência manual.
- `(1)`, `(2)` e similares indicam possível cópia/anexo, nunca V1/V2. V10 (2) mantém V10 como informação textual e alerta sobre o sufixo.
- Múltiplos arquivos podem ser cópias ou versões diferentes. Não são comparados por bytes.
- Outros episódios aparecem em seção separada, sem associação aos takes selecionados.
- Ausência de vídeo pode ser normal antes da geração. Não é reprovação.
- Nomes arbitrários e tipos incompatíveis, como TAKE01.png, exigem associação manual fora deste utilitário.
- Subpastas não são percorridas. Links simbólicos, junções e outros pontos de redirecionamento do Windows são ignorados; a pasta selecionada também não pode ter esses componentes no caminho.
- O relatório é determinístico para a mesma pasta inalterada. Não representa uma captura atômica se outro processo estiver modificando a pasta durante a conferência.

**Identificação por nome não comprova conteúdo real, resolução, identidade, versão aprovada, qualidade, continuidade, voz, lip-sync ou humor.** A revisão humana permanece obrigatória. Arquivos de referência e âncoras 9:16 não são inspecionados visualmente neste piloto.

## Testes e critérios de aceite

```powershell
py -3 -B -m unittest discover -s tests -p "test_production_engine.py" -v
```

Os testes usam diretórios temporários sintéticos. Cobrem números completos, episódios de sete/oito takes, duplicação de extensão, sufixos, versões ambíguas, outros episódios, espaços/acentos, ausência de pasta, acesso negado simulado, saídas texto/JSON, retorno de erro sem traceback, links, metadados de junções Windows, preservação dos bytes/nomes/mtime e resultados repetíveis. Links reais podem exigir privilégios ou modo de desenvolvedor no Windows; o teste informa explicitamente um skip se não puder criá-los.

Validação em 27/10/2026: **13 testes aprovados em Linux, sem skips**, incluindo chamadas reais ao CLI em subprocessos. Permissão negada e atributos de junções Windows foram simulados; links simbólicos foram testados realmente em diretórios sintéticos. O teste nativo no Windows continua pendente. A suíte operacional do Manager não foi repetida, pois nenhum arquivo operacional foi modificado.

Aceite humano: executar e entender o relatório no Windows, identificar todas as ambiguidades previstas, nenhuma associação silenciosa incorreta e nenhuma escrita nos arquivos examinados. Medir o tempo completo de conferência manual versus relatório, incluindo preparação e revisão dos avisos. Meta experimental sugerida: reduzir esse tempo em 20%, sem elevar erros; não é ganho comprovado nem condição de aprovação automática. Um episódio não prova superioridade geral de método.

## Proteção, entrega e próximas autorizações

Branch isolada; somente utilitário, seus testes e este documento. Sem mudanças em `app.py`, interface, iniciador, SQLite, `data`, mídias, backups ou vínculos. Nenhuma dependência nova. Sem Flow, nuvem, créditos, geração de conteúdo ou REF PACK. As diretrizes dos documentos experimentais sobre automações futuras não ampliam esta autorização.

A entrega é um commit para revisão. Merge, instalação e seleção de qualquer acervo real precisam de autorização específica. Não publicar release automaticamente. Relatórios podem expor nomes e caminhos privados: permanecem no terminal local; não publicar logs reais.

## Pendências prioritárias de segurança — fora deste piloto

Preservadas da auditoria de 27/10/2026, sem correções autorizadas nesta etapa:

1. Cópia de mídia e transação SQLite não são atômicas juntas. Interrupção pode deixar destino parcial; arquivo já existente é reutilizado sem conferir novamente seus bytes. Estudar staging, validação e recuperação antes de lote.
2. Restauração é aditiva e pode criar episódios com sufixo “restaurado”. Não usar como atualização ou sincronização; validar recuperação em destino vazio.
3. Exportação não recalcula o hash dos bytes e exclui órfãos. ZIP emitido não certifica integridade nem substitui preservação integral da pasta fechada quando necessária. Restaurar e conferir em ambiente autorizado.
4. Iniciador aceita Python 3.10, mas `hashlib.file_digest` exige 3.11+. Recomendar 3.12 até correção autorizada.
5. Prompts/metadados não têm histórico imutável de todas as edições; editar prompt não reabre revisão e o tratamento de texto remove espaços nas extremidades.
6. Versão instalada, caminhos efetivos, integridade e recuperação do acervo real no Windows não foram certificados nesta etapa. A declaração de backup na exclusão não verifica o backup automaticamente.

Essas pendências exigem uma futura etapa prioritária de segurança, com autorização e testes direcionados. Não ampliar este piloto para tratá-las.
