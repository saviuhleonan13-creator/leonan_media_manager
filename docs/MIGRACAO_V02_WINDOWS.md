# V0.1 → V0.2 no Windows: procedimento para revisão

**Estado: 🟡 EM INVESTIGAÇÃO.** Desenvolvimento e testes sintéticos concluídos não autorizam instalação no acervo principal. Execute os passos com seu acervo somente após revisão do ADM e autorização expressa do operador. Não exclua o PILOTO real nesta etapa de entrega.

## O que foi verificado

A V0.2 utiliza o mesmo esquema SQLite e o mesmo formato de backup `version: 1` da V0.1. Não faz conversão destrutiva nem troca tabelas. Os testes criaram um acervo sintético com o esquema original da V0.1, copiaram a pasta inteira para outro local e abriram a cópia na V0.2: registros, IDs, mídias, miniaturas, versões e estados permaneceram iguais. Também foi testada a exportação/restauração em uma pasta vazia.

Isso verifica o procedimento com dados sintéticos. **Os seus ZIPs de aproximadamente 10,5 MB e 14,7 MB, a pasta original, a cópia de segurança e o ambiente da porta 8766 não foram acessados nem certificados nesta entrega.** A restauração integral de um backup real continua pendente do teste local autorizado.

## Preparação: preservar a V0.1

1. Anote o caminho da pasta de produção e a pasta exata `data` que a V0.1 usa. Se você abre com `--data-dir`, confira esse caminho; não presuma que é a pasta ao lado do programa.
2. Feche a V0.1 e qualquer outra instância que use esse mesmo acervo. Feche pelo terminal com **Ctrl+C** antes de copiar o banco. Não copie um SQLite que ainda está sendo alterado.
3. Mantenha intactos a pasta original, a cópia de segurança e os ZIPs antigos. Se desejar uma cópia adicional, crie outra pasta com nome novo; não substitua backups existentes.
4. Baixe `LEONAN_MEDIA_MANAGER_V0.2.zip` e escolha **Extrair Tudo** em uma pasta nova, por exemplo `Documentos\LEONAN_V02_TESTE`. Ela deve conter uma subpasta `LEONAN_MEDIA_MANAGER_V0.2` com `iniciar.py` e `app.py`.

**Não extraia por cima da V0.1, não mescle pastas e não copie arquivos novos sobre o programa antigo.** O pacote V0.2 não contém `data`, mídias reais, bancos, ambientes virtuais ou credenciais.

## Teste autorizado em cópia independente

1. No Explorador, copie **a pasta `data` inteira** do acervo V0.1 fechado. Cole dentro da pasta nova `LEONAN_MEDIA_MANAGER_V0.2`, criando `LEONAN_MEDIA_MANAGER_V0.2\data`.
2. Antes de colar, confirme que esse destino **não existe**. Se já houver `data`, pare e use outra extração nova; não aceite mesclar nem substituir arquivos. Não use a pasta de backup original como pasta de trabalho.
3. Confira que a nova cópia tem `registry.sqlite3`, `media` e `thumbs`. Copiar apenas o banco não copia as mídias. Não mova a pasta original; use **Copiar**, não **Recortar**.
4. Abra o PowerShell **na pasta nova que contém `iniciar.py`** e execute:

   ```powershell
   py -3 iniciar.py --port 8767 --data-dir ".\data"
   ```

   O caminho explícito `--data-dir` é intencional: evita reutilizar uma variável `LEONAN_DATA_DIR` que possa apontar para produção. A porta **8767** distingue este teste da produção (8765) e do teste anterior (8766). Se 8767 estiver ocupada, escolha outra porta livre; não encerre instâncias desconhecidas.
5. Abra `http://127.0.0.1:8767` e confirme a etiqueta **V0.2**. Confira episódios, números dos takes, versões em uso e históricas, prompts/observações e decisões. Amplie uma imagem e reproduza um vídeo. A pasta V0.1 original deve continuar intacta e fechada.
6. Antes de qualquer exclusão na cópia, exporte um backup novo dessa cópia. Não reutilize o nome dos ZIPs antigos. Para verificar a restauração integral desse ZIP, use outra pasta de dados **nova e vazia**, com outro servidor local:

   ```powershell
   py -3 iniciar.py --port 8768 --data-dir ".\VALIDACAO_RESTAURACAO_VAZIA"
   ```

   Use **Restaurar ZIP** nessa instância vazia e confira todos os episódios/takes, versões, estados, imagens e reprodução dos vídeos. Não restaure em cima da produção; a restauração adiciona episódios, não substitui os existentes.
7. Só após essa conferência e a autorização do operador, execute o roteiro de exclusão na **cópia de teste 8767**, nunca no acervo original: cancele uma confirmação, exclua PILOTO digitando o código, confira a biblioteca e teste um take sintético. Para testar uma exclusão de take do EP04 real, use uma cópia independente e confirme a autorização para essa ação.
8. Exporte depois das exclusões para um arquivo de nome novo e restaure novamente em **outro destino vazio**. Não use a pasta de validação anterior sem conferir que está vazia; se já tem registros, use outro nome novo.

Um ZIP ser aceito não prova sozinho a restauração integral: confira a presença e o conteúdo das mídias, as versões e o vídeo em reprodução. Registre o resultado e envie ao ADM para revisão.

## Conferência antes da aprovação

- [ ] A V0.1 original, a cópia de segurança e os ZIPs anteriores continuam intactos.
- [ ] A V0.2 está em pasta separada, com **cópia independente** de `data` e porta diferente.
- [ ] Os episódios/takes, números, versões e estados foram conferidos antes das exclusões.
- [ ] Um backup anterior às exclusões foi restaurado e conferido em pasta vazia.
- [ ] Cancelar não remove registros.
- [ ] PILOTO sumiu somente na cópia onde o operador confirmou a exclusão.
- [ ] Mídias exclusivas do PILOTO saíram do seletor e da similaridade.
- [ ] Imagem compartilhada, inclusive histórica, continua disponível no outro take.
- [ ] Um take excluído não renumerou nem alterou os demais.
- [ ] Miniaturas, imagem ampliada, vídeo e reversão de versões continuam funcionando.
- [ ] O backup posterior foi restaurado e conferido em **outro** acervo vazio.
- [ ] ADM revisou o resultado; operador autorizou expressamente o próximo passo.

## Retorno à V0.1 e eventual adoção

Para interromper o teste, feche os terminais da V0.2 e reabra a **V0.1 original, com sua pasta original**, sem copiar nada da V0.2 de volta. Nenhum procedimento desta entrega exige remover ou substituir `data` da V0.1.

Se o teste passar, a eventual adoção da pasta V0.2 validada como novo acervo de trabalho depende de aprovação separada. Planeje uma janela sem novas alterações na V0.1, faça uma nova cópia integral do estado mais recente e repita a conferência. Não mantenha as duas versões alterando o mesmo `data`, nem continue produzindo simultaneamente em cópias divergentes.

**Não há autorização de implantação nesta entrega.** O próximo passo é revisão do ADM e decisão expressa do operador.
