# Automacao do STUDIO — requisitos do piloto

ESTADO: proposta de produto, nao funcionalidades implementadas. Este documento publico descreve apenas requisitos tecnicos gerais; o canone privado permanece em sua origem oficial.

## Autorizacoes por lote

- Um pacote de producao expressamente aprovado pelo operador autoriza a execucao de imagens e preparacao de prompts dentro daquele escopo, sem solicitacoes redundantes de permissao entre arquivos.
- A geracao de video paga, gastos, alteracao de dialogo/canone e publicacao sao acoes distintas que exigem permissao propria.
- Revisao editorial do lote final, com correcao de excecoes, em vez de parada obrigatoria entre imagens e prompts.
- Se uma imagem mudar depois de elaborado o prompt, sinalizar que o prompt correspondente precisa de reconciliacao antes do uso.

## Diversidade visual e humor

- O plano de cada take deve ter uma funcao visual diferente quando possivel: plano geral, ponto de vista, detalhe, movimento justificavel, reacao, revelacao de objeto ou mudanca coerente de luz.
- A variedade nao autoriza teletransporte, eixo de camera invertido, alteracao de roupa ou inventar objetos em movimento.
- Uma unica locacao pode gerar um episodio dinamico com mudanca de escala, foco, composicao e progressao da acao; nao forcar deslocamentos sem causa.
- Humor e falas devem ser revisados por humanos quanto a naturalidade, surpresa e consequencia; o sistema nao altera falas aprovadas.
- Elementos de fundo podem convidar a observacao, desde que nao prejudiquem a cena nem introduzam afirmacoes enganosas sobre fatos reais.
- Reservar uma revisao do payoff antes de liberar a edicao e novamente antes da publicacao.

## Edicao por referencia

- Primeira etapa: receber copias autorizadas dos takes brutos e um video final de referencia do proprio operador.
- Extrair tecnicamente cortes sugeridos e trechos de silencio; nao cortar pausas com funcao comica sem revisao.
- Registrar configuracoes conhecidas de legenda, CTA, volume e SFX numa receita editavel, sem presumir compatibilidade com arquivos nativos do CapCut.
- Gerar apenas previa provisoria. A escolha de timing, pertinencia do SFX, licencas e acabamento continuam sujeitos a revisao humana.
- Medir fidelidade ao estilo e tempo real economizado; nao alegar retencao melhor sem dados.

## Segurança e privacidade

- Branch experimental isolada. Nunca editar diretamente a pasta data/ de producao.
- Testes primeiro com midias sinteticas e copias em diretorios temporarios.
- Nao publicar no Git imagens, videos, roteiros internos, prompts completos, credenciais ou backups.
- Sem conexao automatica de Flow/TikTok e sem postagem.
- Nenhum agente deve consultar ou publicar documentos privados sem aprovacao e escopo delimitado.

## Fases

1. MVP A: relatorio de correspondencia por nome em modo somente leitura — implementado parcialmente em production_engine.py.
2. MVP B: proposta de vinculacao em lote + auditoria de versoes e testes de regressao (nao implementado).
3. MVP C: previa de cortes em MP4 de COPIAS com FFmpeg (nao implementado).
4. MVP D: legendas/CTA/SFX baseados em referencia validada pelo operador (nao implementado).
5. Somente depois: integracao segura com a interface do Media Manager, backup/rollback e teste Windows.
