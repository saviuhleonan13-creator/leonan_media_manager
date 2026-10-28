# Candidata isolada V0.3 — integração seletiva

Data da execução: 28/10/2026. Autorização do operador: despacho de 27/10/2026. Estado: EM INVESTIGAÇÃO. Preparação isolada e regressão sintética Linux concluídas; publicação, Windows e uso operacional não autorizados nesta etapa.

## Proveniência e limites

Branch `candidate/v0.3-integracao-sintetica`, criada diretamente de V0.2 `7825a470e2943e9f1cbc2cd80202b40b1016f4b3`. Não houve merge em branches anteriores, push, release ou instalador.

Arquivos selecionados e conferidos byte a byte contra as fontes:

| Origem | Arquivos |
| --- | --- |
| Piloto 01 `1bdd2fe` | `production_engine.py`, `tests/test_production_engine.py`, `docs/PRODUCTION_ENGINE_MVP.md` |
| Piloto 02 corrigido `838d60c` | `app.py`, `tests/test_media_integrity.py`, `docs/PILOTO_02_INTEGRIDADE.md` |

`AGENTS.md` e `docs/PLANO_EDITORIAL_AUTOMACAO.md` da branch experimental não foram incorporados. Nenhuma regra criativa ou autorização experimental foi adotada. Os relatórios dos pilotos são históricos; este documento define o escopo da candidata, sem ampliar autorizações.

O Piloto 01 permanece CLI independente, de leitura, sem botão nem vínculos automáticos. O Piloto 02 preserva cópia temporária, flush/fsync, SHA/tamanho, publicação sem sobrescrita e recusa de reutilização inválida. `app.py` é exatamente a revisão aprovada em testes sintéticos do Piloto 02. Não há funcionalidades operacionais adicionais.

O rótulo de interface permanece V0.2: não houve mudança visual. Os ZIPs históricos V0.1/V0.2 existentes no repositório não são pacotes da candidata; não foram refeitos nem devem ser usados para validá-la.

## Alterações adicionais autorizadas

- `tests/test_deletion.py`, `tests/test_migration.py`, `tests/browser_deletion.py`: `contextlib.closing` nas conexões próprias das fixtures, mantendo o contexto transacional interno e todas as asserções. Sem sleeps, exclusão forçada ou supressão de erros.
- `tests/browser_smoke.py`: a restauração de interface passa a usar outro servidor com diretório novo/vazio; expectativas refletem os dois episódios restaurados sem duplicação. O fluxo anterior está preservado no histórico Git, e o teste unitário legado de restauração aditiva permanece no código.
- `tests/run_candidate_v03.py`: descoberta, detecção de IDs duplicados, exclusões explícitas e execução restrita. Nenhuma alteração dos testes excluídos para obter aprovação.
- `tests/test_integration_v03.py`: quatro casos novos de recuperação integral, esquema, rejeição de arquivos inválidos em destino vazio e recuperação de histórico anterior à exclusão em nova pasta.
- `tests/benchmark_candidate_v03.py`: medição opcional com vídeos gerados localmente, V0.2 lida do Git e bancos temporários novos. Não abre servidor ou acervo preexistente.

## Inventário e resultado final Linux

Ambiente: Python 3.12.14, FFmpeg/ffprobe 7.1.5, Chromium 154.0.8037.57 e Playwright. Fixtures somente sintéticas, em diretórios temporários. Nenhuma pasta real, backup privado ou instalação operacional foi acessada.

| Grupo | Descobertos | Excluídos | Executados |
| --- | ---: | ---: | ---: |
| V0.2 | 42 | 4 | 38 |
| Piloto 01 | 13 | 0 | 13 |
| Piloto 02 corrigido | 17 | 0 | 17 |
| Integração V0.3 | 4 | 0 | 4 |
| Total | 76 | 4 | 72 |

Zero IDs duplicados. Execução final: **72 aprovados, zero falhas, erros ou skips**, 2,573 segundos. A auditoria adicional, com referências de conexões retidas e fechamento explícito verificado antes da limpeza, passou nos mesmos 72 casos e observou **515 conexões, zero abertas ao final**. Essa instrumentação diagnóstica não modifica os testes operacionais.

Comando autorizado para esta seleção:

```sh
.venv/bin/python -B tests/run_candidate_v03.py
```

**Não usar discovery irrestrito nesta candidata:** isso executaria cenários não autorizados. O runner retorna erro se houver falhas ou skips; um skip deve ser reportado, não ocultado.

### Exclusões finais e lacunas

Os testes abaixo permanecem intactos no código e estão excluídos da execução final:

1. `test_app.MediaManagerTests.test_restore_merges_without_overwriting_existing_episode`: restaura duas vezes em banco com episódio existente; explicitamente proibido.
2. `test_app.MediaManagerTests.test_restore_rejects_corruption_without_partial_registry`: tenta restaurar sobre banco preenchido, embora espere rejeição.
3. `test_app.MediaManagerTests.test_restore_rejects_traversal_and_bad_manifest`: também usa banco preenchido; cobertura equivalente de rejeição foi adicionada em destinos novos.
4. `test_deletion.DeletionTests.test_pre_deletion_backup_can_restore_removed_history`: reutiliza o banco após excluir o episódio, ainda contendo registros técnicos de assets e arquivos órfãos. Cobertura substituta usa banco inteiramente novo.

**Ocorrência de escopo registrada:** na primeira rodada desta tarefa e na primeira auditoria de conexões, o quarto caso foi executado porque não restavam episódios/takes. A revisão posterior constatou que o banco ainda tinha assets. Isso não atende ao critério estrito de destino vazio. O caso foi retirado da seleção final, uma alternativa em nova pasta foi adicionada e a seleção final foi executada novamente. Os três primeiros casos nunca foram executados nesta tarefa. Não houve dados reais envolvidos. O resultado preliminar não certifica restauração em banco preenchido nem amplia sua autorização.

### Cobertura funcional

Criação/edição de takes e criação de episódios, importação, reutilização, versões, revisão manual, exclusão transacional, mídia compartilhada/histórica, hashes, falhas de escrita/SQLite, recuperação, reinício e utilitário de nomes passaram nas verificações selecionadas. A V0.2 não fornece edição de episódio; nenhuma funcionalidade inexistente foi adicionada ou declarada testada.

## Navegador

Executados e aprovados, em Chromium:

```sh
python -B tests/browser_smoke.py --python /workspace/leonan_media_manager/.venv/bin/python
python -B tests/browser_deletion.py --python /workspace/leonan_media_manager/.venv/bin/python
```

Cada roteiro escolhe portas locais livres e fornece `--data-dir` explícito sob diretório temporário próprio. Servidores são encerrados pelo roteiro. Não foi usado o servidor operacional ou a porta padrão por configuração fixa.

- Smoke: piloto sintético, vídeo em reprodução, ampliação, criação de episódio/take, importação, notas, versões, revisão, desvinculação, exportação/restauração em servidor vazio, recarga e layout móvel.
- Exclusão: cancelamento, confirmação, erro controlado na UI, exclusão de episódio/take, preservação física, histórico e compartilhamento, seletor sem órfãos, vídeo, comparação/continuidade e restauração em segundo banco vazio.
- Nenhum erro inesperado de JavaScript ou mídia quebrada; verificações de requisições externas passaram. Respostas negativas provocadas pelo teste não representam falhas inesperadas.

O cenário de navegador de restauração sobre banco preenchido não foi executado; essa cobertura continua fora do escopo.

## Backup e recuperação sintética

O novo teste de cópia integral cria versões e um órfão intencional por exclusão autorizada de take sintético. Sem servidor ou conexões abertas, copia a pasta completa para destino inexistente. Compara caminhos, tamanhos e SHA-256 de todos os arquivos, incluindo SQLite, mídias e miniaturas; verifica `integrity_check` e `foreign_key_check`; abre apenas a cópia e confere os registros.

O ZIP exportado dessa cópia preserva episódios, takes, versões, decisões, textos e vínculos ativos/históricos ainda existentes. Confirma-se que a mídia órfã fica fora do ZIP. A restauração ocorre em banco novo/vazio, com comparação semântica de registros e comparação de tamanhos/hashes de mídia. A origem e a cópia integral mantêm seus bytes. Outro teste restaura backup anterior à exclusão em pasta nova e recupera o histórico sem repovoar o banco de origem.

Distinção obrigatória: **ZIP exportado não equivale à cópia integral de dados**. Órfãos físicos e seus registros técnicos não são incluídos no ZIP. Miniaturas são derivadas novamente na restauração. Exportar não recalcula todos os hashes nem prova recuperabilidade sozinho.

Não houve migração de esquema: `SCHEMA` foi comparado literalmente com V0.2 e é idêntico. Um teste compara colunas, FKs e índices com o esquema histórico congelado. Fixtures de compatibilidade V0.1 são artificiais; nenhum banco real foi migrado.

## Medição sintética de desempenho

Comando: `.venv/bin/python -B tests/benchmark_candidate_v03.py`. Requer checkout Git com V0.2 disponível; não executar como parte do reteste Windows comum.

Dois vídeos AVI rawvideo reais, artificiais, gerados por FFmpeg `testsrc2`, 640×360, 30 fps, durações 4 e 16 segundos. Três importações em bancos novos para cada versão/tamanho, alternando a ordem das versões. Medição pelo cliente Flask inclui preparação multipart, cópia recebida, inspeção/miniatura e registro; geração da fixture e hash externo de conferência ficam fora do tempo. Todos os uploads retornaram 201 e os bytes armazenados foram conferidos.

| Tamanho exato | Mediana V0.2 | Mediana candidata | Acréscimo medido |
| --- | ---: | ---: | ---: |
| 41.482.690 bytes (39,56 MiB) | 0,2905 s | 0,3649 s | 0,0744 s / 25,6% |
| 165.907.330 bytes (158,22 MiB) | 0,5447 s | 0,9787 s | 0,4340 s / 79,7% |

Amostras em segundos: V0.2 pequena 0,3086/0,2707/0,2905; candidata pequena 0,3649/0,3628/0,3649; V0.2 grande 0,6655/0,5341/0,5447; candidata grande 0,9787/1,0007/0,9473.

Picos temporários observados por amostragem a cada aproximadamente 2 ms, dentro da pasta de dados: pequena 41.499.843 bytes V0.2 e 82.982.533 candidata; grande 165.924.483 e 331.831.813 respectivamente. A candidata mantém a cópia recebida e o staging ao mesmo tempo. Somar nomes de arquivo pode contar duas vezes o mesmo conteúdo durante o hard link. Deduplicando por inode, os maiores tamanhos lógicos observados da pasta de dados foram 81.947.843/83.045.270 bytes (pequena V0.2/candidata) e 331.868.677/331.894.550 (grande).

Esses valores não medem blocos físicos alocados, memória, o spool multipart fora da pasta de dados nem o pico exato entre amostras. O arquivo-fonte e ambientes de teste também ocupam espaço separado. A varredura adiciona overhead nas duas versões. Cache não foi esvaziado, o ambiente é Linux rápido e há apenas três repetições; não extrapolar para Windows, disco externo, rede, vídeos de 1 GiB ou codecs típicos do Flow. Não há benchmark de reuso, exportação ou restauração grande nesta etapa. A proteção tem custo mensurável, ainda sujeito a avaliação no notebook.

## Futuro Windows — proposta, não execução autorizada

Após autorização e publicação, extrair a revisão exata em pasta nova, sem usar ZIPs históricos incluídos no repositório e sem sobrepor qualquer instalação. Em PowerShell nessa pasta, executar separadamente:

```powershell
py -3.12 --version
py -3.12 -m venv .venv-v03-teste
.\.venv-v03-teste\Scripts\python.exe -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
.\.venv-v03-teste\Scripts\python.exe -B tests/run_candidate_v03.py
$LASTEXITCODE
```

Confirmar Python 3.12.10 do notebook e FFmpeg/ffprobe; os testes completos de vídeo precisam deles. Resultado pretendido: 76 descobertos, 4 excluídos, 72 executados, zero falhas/erros/skips, código 0. A ressalva anterior de link simbólico do Piloto 01 pode reaparecer; nesse caso o runner retorna 1 e a lacuna deve ser reportada, sem usar administrador nem desativar proteções.

Para os dois roteiros de navegador, somente após autorização para instalar dependências de teste no ambiente isolado:

```powershell
.\.venv-v03-teste\Scripts\python.exe -m pip install playwright
.\.venv-v03-teste\Scripts\python.exe -m playwright install chromium
.\.venv-v03-teste\Scripts\python.exe -B tests/browser_smoke.py --python "$PWD\.venv-v03-teste\Scripts\python.exe"
.\.venv-v03-teste\Scripts\python.exe -B tests/browser_deletion.py --python "$PWD\.venv-v03-teste\Scripts\python.exe"
```

Os scripts iniciam apenas servidores sintéticos próprios. Não executar `iniciar.py`, atalhos operacionais, discovery irrestrito ou apontar para dados reais. Enviar versão Python, saída completa, códigos e skips; não declarar aprovação nativa a partir dos resultados Linux. Ctrl+C interrompe; não limpar pastas antigas nem copiar resultados para produção.

## Retorno seguro e riscos restantes

Nesta etapa basta encerrar os testes e deixar de usar a candidata: o programa operacional e seu acervo não foram alterados. Branches anteriores e histórico permanecem preservados.

Uma futura adoção exigiria autorização separada, identificação da pasta efetiva, encerramento de instâncias, checkpoint integral verificado e restauração isolada comprovada antes de escrever em uma cópia de trabalho. Manter a instalação original intacta; não mesclar diretórios nem restaurar ZIP sobre banco preenchido. Reutilizar ambientes quando seguro, sem impor número arbitrário de backups nem excluir cópias existentes.

Se houver produção nova na candidata, voltar simplesmente ao banco antigo perderia trabalho. Antes de retorno, preservar integralmente o estado mais recente e planejar reconciliação/recuperação autorizada; não sobrescrever o original. O mesmo esquema não basta para garantir retorno sem perdas após novas gravações.

Persistem os limites dos pilotos: queda de energia não certificada, ausência de transação única arquivo/SQLite, órfãos preservados, alterações externas depois do hash, hard links dependentes do sistema de arquivos, possível recusa conservadora de miniatura divergente, concorrência entre múltiplos servidores não homologada, exportação sem nova conferência integral e restauração aditiva capaz de duplicar episódios. Não foram corrigidos neste escopo. O iniciador ainda tem a divergência histórica de Python mínimo; usar 3.12 no ensaio proposto.

Critério de aceite desta entrega: nenhuma regressão identificada nas verificações autorizadas da seleção final; não constitui liberação operacional. Próximas decisões separadas: revisão do commit; push controlado; testes Windows da candidata; ensaio com cópia real; eventual adoção. Nenhuma é presumida pela aprovação sintética Linux.
