# Production Engine — MVP 0.1 (somente leitura)

Estado: EM INVESTIGACAO. Branch experimental. Nao substitui o Media Manager.

## Teste no Windows

Coloque COPIAS de algumas imagens e videos em uma pasta isolada. Na raiz do projeto, execute:

    py -3 production_engine.py --source "C:\\caminho\\COPIAS_EP14" --episode EP14 --expected-takes 7

O comando apenas le os nomes dos arquivos e imprime um relatorio JSON. Nao modifica, copia, importa, renomeia ou exclui midias ou bancos SQLite.

## Regras

- Identifica imagens por nomes como EP14_IMG05.png e EP14_IMG05_V2.png.
- Identifica videos por nomes como EP14_TAKE05.mp4 e EP14_T05_V1.4.mp4.
- Sufixo (1) em anexo nao significa versao V1.
- Videos Flow sem numero do take sao marcados como nao identificados.
- Multiplas candidatas geram alerta; nenhuma e escolhida automaticamente.
- Nenhum relatorio aprova voz, lip-sync, humor, direitos ou postagem.
- So lista a pasta informada (nao percorre subpastas).
- Nao enviar arquivos de producao ou logs com dados privados a repositorios publicos.

## Testes

    py -3 -m unittest discover -s tests -p "test_production_engine.py" -v

Proximos passos: validar com copias, mapear arquivos ambiguos mediante revisao, testar importacao em lote em acervo isolado, e so depois estudar a pre-edicao em MP4.
