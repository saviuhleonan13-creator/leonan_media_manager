# Relatório de validação · V0.2

**Data: 21/10/2026 · Estado: 🟡 EM INVESTIGAÇÃO — pronto para revisão do ADM, sem autorização de implantação.**

## Alterações

- Exclusão manual de episódio com resumo do escopo, digitação do código e declaração de backup válido.
- Exclusão de take com identificação de episódio, número e descrição, sem renumerar os demais.
- Confirmações vinculadas ao conteúdo conferido, com expiração e bloqueio de solicitações repetidas/antigas, inclusive quando SQLite reutiliza IDs.
- Exclusão de registros em transação única, com chaves estrangeiras ativas e mensagem de erro em vez de sucesso quando o banco falha.
- Biblioteca, similaridade e exportação passam a considerar apenas mídias com vínculos ativos **ou históricos**. Mídias órfãs e miniaturas permanecem fisicamente no disco, com seu registro técnico preservado.

Nenhuma dependência nova, conversão de esquema SQLite, limpeza física, alteração de fluxo de geração ou integração externa. O formato do backup permanece `leonan-media-manager`, versão 1. O iniciador Windows e a lógica de copiar mídias foram preservados.

## Evidências automatizadas

Ambiente: Linux, Python 3.12, FFmpeg/ffprobe 7.1 e Chromium. Todos os dados de teste foram gerados sinteticamente em diretórios temporários. **42 testes passaram, sem falhas e sem skips**: 20 regressões da V0.1, 20 testes de exclusão e 2 de compatibilidade/migração.

```sh
.venv/bin/python -m unittest discover -s tests -v
```

| Requisito | Evidência | Resultado |
| --- | --- | --- |
| Excluir PILOTO preservando EP04 | Testes de exclusão com episódios sintéticos e interface real | Passou |
| Remover PILOTO da lateral | Navegação e confirmação no Chromium | Passou |
| Retirar mídias exclusivas do seletor e da similaridade | Comparação de IDs na API e opções reais do seletor | Passou |
| Excluir um take sem alterar os outros | Comparação de todos os registros, números e vínculos remanescentes | Passou |
| Proteger imagem/vídeo compartilhados | Vínculos entre takes e episódios; imagem mantida apenas no histórico; vídeo compartilhado com reprodução | Passou |
| Preservar versões e reversão | Histórico antes/depois e escolha de versão anterior pela interface | Passou |
| Cancelamento e confirmação explícita | Abrir/cancelar sem remoção, código errado e checkbox obrigatório, no navegador | Passou |
| IDs inválidos e repetição | IDs inexistentes, alvo incorreto, confirmações expiradas/alteradas e IDs recriados | Passou |
| Falhas de banco | Trigger SQLite interrompe a operação após remoção de vínculos; rollback confere todos os registros; falha de commit e banco indisponível também simulados | Passou |
| Exportar e restaurar após exclusão | ZIP posterior restaurado em acervo vazio; comparação semântica de episódios, takes, mídias, versões e estados | Passou |
| Vídeo, miniaturas e referências | Reprodução no Chromium antes/depois de restauração, leitura de miniaturas e requisições parciais HTTP | Passou |
| Preservar originais e cópias locais | SHA-256 dos arquivos de mídia/miniaturas antes e depois das exclusões | Passou |
| Integridade SQLite | `PRAGMA integrity_check` e `PRAGMA foreign_key_check` após operações e falhas | Passou |
| Copiar acervo V0.1 para nova pasta | Esquema histórico da V0.1, acervo sintético fechado e cópia integral; bytes/IDs/registros preservados | Passou |
| Restaurar backup V0.1 | Backup no formato original restaurado na V0.2, preservando histórico e estado | Passou |

## Interface real

Os dois roteiros passaram em Chromium, com servidores e acervos temporários separados:

```sh
python tests/browser_smoke.py --python .venv/bin/python
python tests/browser_deletion.py --python .venv/bin/python
```

O primeiro preserva o percurso da V0.1: criar episódios/takes, importar, ampliar, reproduzir, trocar versão, decidir, exportar/restaurar e navegar em viewport móvel.

O segundo cria PILOTO e EP04 **sintéticos**, verifica confirmações/cancelamentos, provoca uma resposta de erro para conferir a interface, exclui os registros autorizados pelo teste, confere histórico/reuso, reproduz o vídeo restante e restaura o ZIP posterior em outro acervo vazio. A validação também confere modal/layout em viewport móvel. Não houve erro de JavaScript nem referências de mídia quebradas. Os requests de erro 400/503 provocados intencionalmente pelo teste não são relatados como falhas inesperadas.

## Pacote e preservação da V0.1

A entrega V0.2 fica na branch `v0.2-exclusao-segura`. A branch `main`, o código e o ZIP da V0.1 permanecem preservados. O ZIP V0.2 contém código, dependências fixadas, documentação e testes/fixtures sintéticos, com manifesto SHA-256. Não contém `data`, `.venv`, SQLite, mídia do operador, backup privado, cache, credencial nem a cópia do ZIP da V0.1.

## Limites e pendências

- A V0.1 foi informada como funcionando no Windows pelo operador. **A V0.2 não foi executada nativamente em Windows** nesta entrega; o teste final no notebook depende da autorização expressa do operador.
- Os ZIPs reais de aproximadamente 10,5 MB e 14,7 MB, a pasta de produção, sua cópia de segurança e o ambiente da porta 8766 **não foram acessados nem modificados**. Nenhum desses backups foi certificado como integralmente restaurável aqui.
- A compatibilidade do procedimento foi verificada com acervos sintéticos; não substitui a conferência de uma restauração integral do acervo real em uma pasta local vazia e isolada.
- A V0.2 não libera espaço em disco e não tem lixeira/undo. Recuperação do histórico depende de backup anterior à exclusão. Uma limpeza futura de órfãos precisa de aprovação e tarefa específicas.
- Nada foi instalado no acervo principal. Não houve exclusão do PILOTO real nem autorização implícita para implantação.

**Próximo passo: revisão do ADM e autorização expressa do operador para o teste final isolado, seguindo [MIGRACAO_V02_WINDOWS.md](MIGRACAO_V02_WINDOWS.md).**
