# V0.3 — preservação de assets.created_at

28/10/2026. Implementação localizada e regressão Linux autorizadas; publicação, Windows e uso operacional pendentes. Branch `fix/v03-preservar-created-at`, baseada em `4a295c3ebf84865a75fde65cd53964d5497d682a`. Nenhum acervo real foi usado. Não houve alteração de interface, release, merge ou push nesta entrega.

## Diagnóstico e semântica

Na V0.2 e na candidata anterior, a exportação incluía `assets.created_at`, mas a restauração ignorava esse valor e criava o asset com `CURRENT_TIMESTAMP`. O teste integral podia passar se tudo ocorresse no mesmo segundo. O reteste Windows com raiz curta isolou essa divergência após desaparecerem os quatro problemas anteriores relacionados a caminhos longos.

`created_at` é a data original de cadastro da mídia no registro. Não é data do arquivo, da restauração ou de aprovação. Datas SQL padrão são tratadas como UTC, sem conversão de fuso nesta correção.

## Correção e política

- `validate_archive` valida todas as datas antes de copiar mídias para destinos definitivos ou gravar novos registros. O upload do ZIP e sua leitura temporária continuam necessários.
- Formato exato ASCII `YYYY-MM-DD HH:MM:SS`, sem espaços adicionais, timezone, frações ou normalização. O calendário é validado com `datetime.strptime`; ano 0000, dias impossíveis, hora 24 e segundos 60 são recusados.
- Datas válidas são passadas como parâmetro opcional a `store_media` e incluídas por SQL parametrizado apenas na inserção de asset novo. Datas futuras bem formadas são aceitas, sem alegação de autenticidade.
- Importação comum continua omitindo a data e usando o default SQLite. Deduplicação retorna o asset existente sem atualizar seu timestamp.
- Campo ausente continua aceito. O registro novo recebe o default SQLite da restauração. A resposta JSON contém `warnings`, com `code: created_at_missing`, `asset_id` do manifesto, SHA e mensagem de que a data original não foi recuperada. Registros reutilizados preservam sua data. Não há alteração da interface: o aviso está na resposta da API e não foi adicionado visualmente ao aplicativo.
- Campo presente inválido (inclusive null, número, booleano, lista, objeto, string vazia ou conteúdo adicional) retorna 400 antes das gravações de registros e da publicação de mídias.
- SHA repetido com datas distintas é recusado. Uma ocorrência sem data e outra com data também é ambígua e recusada. Repetições com a mesma data, ou todas sem data, mantêm deduplicação; avisos de ausência identificam cada registro de origem afetado.
- Formato de backup continua `leonan-media-manager`, versão 1. Esquema SQLite não mudou. Exportação, publicação segura, validação de bytes e função de vinculação foram comparadas por AST com a base e permanecem idênticas.

## Testes e resultados executados

Ambiente Linux, Python 3.12.14. Todas as fixtures são sintéticas; restaurações somente em bancos inicialmente vazios. Não houve sleeps, relaxamento de asserções ou restauração em banco preenchido nesta tarefa.

Controle negativo: o teste integral de roundtrip, usando datas fixas antigas, foi executado contra o código da revisão `4a295c3` carregado isoladamente em memória. Falhou exatamente por trocar as datas antigas pelo horário atual. Esse FAIL esperado demonstra o defeito anterior e não é resultado da versão corrigida.

Oito novos testes de `tests/test_asset_timestamps.py` passaram:

1. Datas antigas distintas exportadas no manifesto e preservadas em restauração, com comparação integral de assets, episódios, takes e vínculos e conferência dos hashes.
2. Campo ausente: default SQLite dentro dos limites observados antes/depois, sem espera, e aviso estruturado correto; outra mídia continua com sua data original.
3. Dezenove entradas inválidas em subcasos, sempre em destino novo: erro 400, banco byte a byte inalterado e nenhuma publicação de mídia/miniatura.
4. SHA repetido com datas conflitantes, inclusive presença versus ausência: recusa anterior às gravações.
5. SHA repetido com mesma data: restauração deduplicada, mantendo timestamp e vínculos.
6. Importação comum: data padrão; reimportação e novo vínculo não alteram uma data antiga existente.
7. Falha SQLite após preparação das mídias: rollback dos assets, timestamps, episódios, takes e vínculos. Cópias físicas podem permanecer órfãs, conforme política anterior.
8. Data futura válida preservada exatamente.

O teste antigo `test_export_restore_portable_roundtrip_with_versions_and_status` agora atribui datas sintéticas fixas (2001 e 2002) antes da exportação e mantém a comparação integral. O auxiliar de comparação em `tests/test_media_integrity.py` deixou de excluir `created_at`; a cobertura ficou mais rigorosa.

### Inventário final

- 76 casos anteriores + 8 novos = **84 descobertos**.
- **4 excluídos**, preservados no código e não executados.
- **80 executados e aprovados**, zero falhas, erros ou skips, em 3,229 segundos.
- Testes de navegador **não executados**, conforme restrição até revisão da regressão.

Exclusões inalteradas:

- `test_app.MediaManagerTests.test_restore_merges_without_overwriting_existing_episode`
- `test_app.MediaManagerTests.test_restore_rejects_corruption_without_partial_registry`
- `test_app.MediaManagerTests.test_restore_rejects_traversal_and_bad_manifest`
- `test_deletion.DeletionTests.test_pre_deletion_backup_can_restore_removed_history`

O runner agora confere contagem e hash da lista ordenada de IDs antes da execução, além de duplicações e presença das exclusões. Uma verificação diagnóstica com caso adicional simulado confirmou recusa antes de executar testes. Não foram criadas exclusões novas.

SHA-256 do inventário (IDs ordenados, unidos por LF, sem LF final):
`d33754090ea6824977b965cfcc7623d25246252791522ec797a3a19540866974`

SHA-256 de `tests/run_candidate_v03.py`:
`8f9254623f948950be3d955e8c9c651b8af6b05584bb8cc184d658402a07c391`

Comando Linux executado: `.venv/bin/python -B tests/run_candidate_v03.py`.

## Proposta de reteste Windows — após autorização e publicação

Receber esta revisão exata em pasta nova, sem sobrepor a instalação operacional. Não executar `iniciar.py`, discovery irrestrito ou navegadores nesta etapa. Python esperado: 3.12.10; FFmpeg e ffprobe devem continuar disponíveis.

Em PowerShell na nova pasta, um comando por vez, interrompendo em qualquer erro:

```powershell
py -3.12 --version
py -3.12 -m venv .venv-v03-timestamp
$pythonPiloto = (Resolve-Path ".\.venv-v03-timestamp\Scripts\python.exe").Path
& $pythonPiloto -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

Raiz curta fora da extração, exclusiva desta sessão:

```powershell
$tempPiloto = Join-Path $env:LOCALAPPDATA ("lm03-" + [guid]::NewGuid().ToString("N").Substring(0,8))
if ($tempPiloto.Length -gt 90) { throw "Raiz longa: interrompa e informe." }
New-Item -ItemType Directory -Path $tempPiloto -ErrorAction Stop | Out-Null
$env:TEMP = $tempPiloto
$env:TMP = $tempPiloto
$env:TMPDIR = $tempPiloto
& $pythonPiloto -B -c "import tempfile; print(tempfile.gettempdir())"
```

Conferir o runner e executar a seleção:

```powershell
$hashRunner = (Get-FileHash -Algorithm SHA256 .\tests\run_candidate_v03.py).Hash
if ($hashRunner -ne "8f9254623f948950be3d955e8c9c651b8af6b05584bb8cc184d658402a07c391") { throw "Runner divergente. Pare." }
& $pythonPiloto -B tests/run_candidate_v03.py
$LASTEXITCODE
```

Esperado para aprovação integral: 84 descobertos, 4 excluídos, 80 executados, `OK`, zero erros/falhas/skips e código 0. O WinError 1314 de links simbólicos continua sendo uma ressalva independente: se reaparecer somente esse skip, serão 79 aprovados e 1 skipped, com código 1. Não converter isso em aprovação nem pedir privilégios elevados. Enviar o log para decisão do operador.

O runner e seus hashes antigos não valem para este inventário. Manter a raiz curta e registrar seu comprimento; a correção de timestamp não altera suporte a caminhos longos. Ctrl+C interrompe; nenhuma limpeza de pastas anteriores ou do operador é solicitada.

## Riscos, compatibilidade e retorno

A data do manifesto é metadado declarado, não prova de autenticidade. Não há assinatura digital. Backups antes tolerados com campo presente malformado ou SHA repetido e datas conflitantes passam a ser recusados; não serão corrigidos silenciosamente. Backups sem a data continuam aceitos com aviso, mas não recuperam uma informação inexistente. A interface não mostra o novo aviso nesta etapa.

Nenhuma restauração em acervo preenchido foi executada; sua política não mudou e não foi homologada. Os riscos anteriores de energia, órfãos, exportação, concorrência e sistema de arquivos permanecem. A preservação de datas não autoriza instalação operacional.

Não houve implantação: encerrar o teste e deixar de usar esta branch basta para voltar ao estado anterior. Não copiar bancos ou mídias sintéticos para produção. O esquema não mudou; não há migração a desfazer. Push, Windows, merge e uso real dependem das respectivas autorizações posteriores.
