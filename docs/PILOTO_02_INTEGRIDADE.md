# Piloto 02 — cópia íntegra e reutilização verificada

Data: 27/10/2026. Estado: EM INVESTIGAÇÃO; implementação e testes sintéticos Linux concluídos, revisão pendente. Push, instalação, Windows e uso real exigem autorização posterior.

## Base e escopo

Branch `pilot02/integridade-midias`, criada de `7825a470e2943e9f1cbc2cd80202b40b1016f4b3` (V0.2). As referências remotas foram conferidas antes de iniciar. O Piloto 01 não foi integrado: sua branch e seu commit permanecem independentes, com a aprovação Windows e ressalva já relatadas pelo operador.

Somente `app.py`, `tests/test_media_integrity.py` e este documento mudaram. Sem alteração de esquema SQLite, interface, política aditiva de restauração, estados editoriais ou dependências. Sem acesso ao acervo real, instalação operacional ou arquivos privados.

## Mecanismo

1. A importação já recebe uma cópia em uma área temporária; `prepare_media` calcula sua referência SHA-256. A restauração compara previamente o conteúdo recebido com o manifesto do backup.
2. `publish_verified` cria um temporário exclusivo `.leonan-copy-*` no diretório de destino, copia os bytes, executa flush/fsync e fecha o arquivo.
3. O temporário é conferido contra SHA-256 e tamanho esperados. Calcular um hash sem compará-lo não é considerado validação.
4. `os.link` publica o arquivo completo sem substituir destino existente. Temporário e destino estão no mesmo sistema de arquivos. Não há fallback para renomeação com substituição ou cópia direta no destino.
5. Se houver colisão, o destino existente é verificado contra a referência. Divergência, ausência, acesso negado ou tipo de arquivo inadequado recusam a operação.
6. Mídia já registrada é verificada antes da reutilização, inclusive pelo seletor de vínculos e reativação de versão histórica. A ausência do arquivo não dispara reparação automática.
7. A nova miniatura também passa por publicação verificada. Uma miniatura preexistente divergente da nova derivação não é sobrescrita: a operação falha de modo conservador. Miniaturas de mídias já cadastradas não são revalidadas/reparadas por este piloto.
8. Os novos registros só podem ser confirmados depois das verificações. A restauração mantém sua transação única e não anuncia sucesso quando há falha.

Falhas de armazenamento retornam HTTP 503 com explicação. SHA incorreto no backup segue retornando 400. Falhas SQLite nas rotas de importação/restauração/vinculação retornam erro de banco, sem mensagem enganosa de episódio duplicado.

Somente o temporário exclusivo da chamada atual é removido no encerramento normal, inclusive em erro. Nunca é removido o destino publicado ou preexistente. Interrupção abrupta pode deixar temporário parcial; falha do banco pode deixar mídia completa sem vínculo. Esses resíduos são preservados, não representam aprovação e não recebem limpeza automática.

## Evidências executadas

Linux, Python 3.12, FFmpeg/ffprobe disponíveis. Todos os acervos foram criados sinteticamente em diretórios temporários. Nenhum teste provocou esgotamento real de disco.

- Primeira execução direcionada: 13 novos testes passaram.
- Execução final após ampliar cobertura: **59 testes passaram, zero falhas, zero erros e zero skips**, sendo 17 novos e 42 regressões existentes.
- `git diff --check`: sem erros.
- A interface de navegador não foi retestada neste piloto. Não foi executado teste nativo Windows.

### Desvio de procedimento registrado

A execução completa das 42 regressões incluiu o teste legado `test_restore_merges_without_overwriting_existing_episode`, que restaura em acervo sintético preenchido. Isso excedeu a restrição desta etapa de testar restauração somente em destino vazio. Nenhum acervo real foi envolvido, e o teste e a política aditiva não foram modificados. Os novos cenários de restauração partem de SQLite vazio; repetição após falha também mantém o banco vazio, podendo existir cópia física órfã. Na futura execução Windows, usar o comando direcionado abaixo, sem repetir o teste legado.

### Cobertura nova (17 testes)

- Cópia completa e repetição com destino correto, sem alterar seu mtime.
- Hash de referência incorreto, tamanho esperado incorreto e corrupção do temporário.
- Destino existente divergente preservado.
- Interrupção de escrita, falta de espaço, permissão e I/O simulados, seguidos de nova tentativa.
- Falha de fsync e publicação sem suporte/permissão, sem fallback.
- Duas operações concorrentes chegando juntas à publicação: mesmo conteúdo (ambas válidas) e conteúdos conflitantes (um vencedor e uma recusa).
- Subprocesso realmente encerrado por `os._exit(73)` durante a escrita; destino final ausente, temporário preservado e repetição bem-sucedida.
- Mídia registrada corrompida/ausente: recusa na importação, vinculação e/ou reativação; registros anteriores preservados.
- Falha na importação com registros e arquivos anteriores inalterados.
- Falha SQLite depois da publicação e nova tentativa reutilizando cópia íntegra.
- Falha de commit com rollback.
- Exportação/restauração em destino vazio, comparando registros, histórico, versões, estado, prompt e bytes; IDs coincidem nessa fixture; timestamps de criação não são usados como critério de equivalência.
- Falha na segunda mídia restaurada: rollback completo do registro, preservação da primeira cópia íntegra e repetição bem-sucedida.
- Falha SQLite após criação de registros na restauração: rollback de todas as tabelas envolvidas.
- Destino físico corrompido em acervo com banco vazio: erro, preservação dos bytes preexistentes.
- Hash do manifesto divergente: restauração recusada sem novos vínculos.

## Limites e riscos remanescentes

- Windows ainda não validado. Hard links são diferentes de links simbólicos: o WinError 1314 do Piloto 01 não comprova falha deste mecanismo. Será necessário testar em volume local NTFS. Sistemas sem suporte são recusados; não oferecer fallback inseguro.
- Concorrência testada com duas threads no publicador. Não se certificou múltiplos servidores Flask escrevendo no mesmo acervo. SQLite ainda pode recusar concorrência; não executar instalações simultâneas sobre a mesma pasta.
- Arquivos e banco não formam uma transação única. Resíduos órfãos são possíveis e intencionais em falhas; não usar sua presença como sucesso.
- fsync do arquivo não é garantia universal de recuperação após queda de energia, falha de controlador ou corrupção do sistema de arquivos. Não foi testada interrupção elétrica nem garantida persistência da entrada de diretório em todos os sistemas.
- Não há proteção contra outro programa que altere/substitua mídia ou diretórios durante/depois da validação. As cópias do Manager devem permanecer sob seu controle; a validação não certifica integridade futura.
- O SHA do banco/manifesto é a referência assumida; não é assinatura digital nem prova de identidade editorial. Alteração coordenada de banco/manifesto e bytes não é detectada como fraude.
- Variação de geração de miniaturas entre versões de Pillow/FFmpeg pode causar recusa conservadora de thumbnail órfã diferente, exigindo diagnóstico posterior, nunca substituição silenciosa.
- A exportação ainda não recalcula SHA, exclui órfãos e não certifica sozinha recuperabilidade. Restauração continua aditiva e pode duplicar episódios se usada em destino preenchido. Esses pontos continuam prioritários e fora deste piloto.
- Não foi executado benchmark de vídeo grande. Na importação individual nova, há aproximadamente três leituras completas adicionais (temporário, destino e vínculo), além de fsync. Ordem de grandeza do acréscimo: `3 × tamanho / taxa efetiva de leitura`, mais hashing e sincronização; cache e concorrência alteram o resultado. Para 1 GiB e 100–500 MiB/s, isso representa cerca de 6–31 segundos de leitura adicional, estimativa ilustrativa, não medição. Reimportação registrada acrescenta aproximadamente duas leituras completas. Restauração nova usa duas verificações adicionais no publicador, além da conferência já existente do backup.

## Roteiro Windows — somente após autorização posterior

1. Receber a revisão aprovada em pasta nova. Não extrair por cima da instalação operacional. Não copiar acervo real, não abrir atalhos e não executar `iniciar.py`.
2. Abrir PowerShell na pasta dessa revisão e executar `py -3.12 --version`. Registrar a versão efetiva; se ausente, interromper e informar. Preferir volume local NTFS; não usar rede, sincronização ou pastas redirecionadas.
3. Preparar um ambiente de teste separado. Estes comandos instalam apenas dependências públicas nessa pasta de teste:

```powershell
py -3.12 -m venv .venv-piloto02
.\.venv-piloto02\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-piloto02\Scripts\python.exe -B -m unittest discover -s tests -p "test_media_integrity.py" -v
```

Os 17 testes criam seus próprios bancos, mídias e backups artificiais em diretórios temporários e encerram essas fixtures ao terminar. Não usam `data` operacional nem a variável `LEONAN_DATA_DIR`; fornecem caminhos explícitos. O arquivo `app.py` é importado pelas fixtures, mas não inicia servidor nem cria a pasta padrão ao ser importado. Não é necessário abrir o navegador ou fornecer arquivos reais. O teste direcionado usa PNG sintético e não exige FFmpeg.

4. Esperado: `Ran 17 tests` e `OK`, sem skips. Erro de hard link, permissão, divergência ou traceback requer interrupção e diagnóstico; não usar administrador nem desabilitar proteções por tentativa.
5. Enviar versão Python, resumo e erros ao responsável. Não declarar sucesso Windows antes de examinar esses resultados.
6. Para parar, Ctrl+C na janela do teste. Não executar limpeza no acervo. Uma interrupção pode deixar fixtures temporárias; não removê-las automaticamente.

## Reversão e próximas decisões

Não houve implantação. Encerrar o teste e deixar de usar esta branch é suficiente; a instalação operacional e a branch V0.2 continuam preservadas. Não copiar banco/mídias de teste de volta e não fazer downgrade sobre pasta de produção. Não é necessária migração reversa porque o esquema não mudou.

Push desta branch, teste Windows, merge e uso real são decisões posteriores distintas. Este documento não autoriza nenhuma delas. Solicitar inicialmente revisão e autorização apenas para push controlado e teste sintético Windows; manter integração e acervo real bloqueados.
