'use strict';
const $ = (selector, parent = document) => parent.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusLabels = {investigating:'EM INVESTIGAÇÃO', approved:'APROVADO', discarded:'DESCARTADO'};
const statusEmoji = {investigating:'🟡', approved:'🟢', discarded:'🔴'};
let state = {episodes:[], takes:[], assets:[], bindings:[], similarities:[]};
let episodeId = null, takeId = null, busy = false, dirty = false, dialogSubmit = null, toastTimer;
const assetById = id => state.assets.find(a => a.id === Number(id));
const currentEpisode = () => state.episodes.find(e => e.id === episodeId);
const currentTake = () => state.takes.find(t => t.id === takeId);
const takesForEpisode = () => state.takes.filter(t => t.episode_id === episodeId).sort((a,b) => a.number - b.number);
const bindingsFor = (id, kind) => state.bindings.filter(b => b.take_id === id && (!kind || b.kind === kind));
const activeBinding = (id, kind) => bindingsFor(id,kind).find(b => b.active);
const pad = number => String(number).padStart(2,'0');

function friendly(binding, take = currentTake(), episode = currentEpisode()) {
  const label = binding.label || take.title;
  const version = binding.version ? `V${binding.version.replace(/^v/i,'')}` : 'versão não identificada';
  return `${episode.code} ${binding.kind === 'image' ? 'IMG' : 'TAKE'}-${pad(take.number)} ${version}${label ? ` — ${label}` : ''}`;
}

async function api(path, options = {}) {
  const headers = {'X-App-Token': $('meta[name="app-token"]').content, ...options.headers};
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {...options, headers});
  let result;
  try { result = await response.json(); } catch { throw new Error('O servidor não respondeu como esperado. Confira se o aplicativo está aberto.'); }
  if (!response.ok) throw new Error(result.error || 'Não foi possível concluir a operação.');
  return result;
}

function toast(message, error = false) {
  const box = $('#toast');
  clearTimeout(toastTimer);
  box.textContent = message; box.className = error ? 'error' : ''; box.hidden = false;
  toastTimer = setTimeout(() => { box.hidden = true; }, error ? 10000 : 5500);
}

async function saveDraft(silent = true) {
  if (!dirty || !currentTake()) return;
  const form = $('#take-form');
  if (!form.reportValidity()) throw new Error('Confira os campos do take antes de continuar.');
  const data = Object.fromEntries(new FormData(form));
  data.number = Number(data.number);
  await api(`/api/takes/${takeId}`, {method:'PATCH', body:data});
  Object.assign(currentTake(), data);
  dirty = false;
  const indicator = $('#save-indicator');
  if (indicator) indicator.textContent = 'Informações salvas';
  if (!silent) toast('Informações do take salvas.');
}

async function run(action, label = 'Salvando…') {
  if (busy) return;
  busy = true;
  const indicator = document.createElement('div');
  indicator.className = 'busy-label'; indicator.textContent = label; indicator.setAttribute('role','status');
  document.body.append(indicator);
  document.body.setAttribute('aria-busy','true');
  const buttons = [...document.querySelectorAll('button')];
  buttons.forEach(button => { button.disabled = true; });
  try { await saveDraft(); await action(); }
  catch (error) { toast(error.message, true); }
  finally {
    busy = false; indicator.remove(); document.body.removeAttribute('aria-busy');
    buttons.forEach(button => { button.disabled = false; });
  }
}

async function reload() {
  state = await api('/api/state');
  if (!state.episodes.some(e => e.id === episodeId)) episodeId = state.episodes[0]?.id ?? null;
  const takes = takesForEpisode();
  if (!takes.some(t => t.id === takeId)) takeId = takes[0]?.id ?? null;
  render();
}

function render() {
  $('#episodes').innerHTML = state.episodes.length ? state.episodes.map(ep => {
    const takes = state.takes.filter(t => t.episode_id === ep.id);
    return `<button class="episode-button ${ep.id === episodeId ? 'active' : ''}" data-action="episode" data-id="${ep.id}" ${ep.id === episodeId ? 'aria-current="page"' : ''}><span class="episode-icon">▤</span><span><strong>${esc(ep.code)}</strong><small>${takes.length} takes · ${takes.filter(t => t.status === 'approved').length} aprovados</small></span></button>`;
  }).join('') : '<p class="sidebar-empty">Seus episódios aparecerão aqui.</p>';
  if (!state.episodes.length) {
    $('#app').innerHTML = `<section class="empty-state"><div class="empty-illustration" aria-hidden="true"><div></div><div>▧</div></div><p class="eyebrow">DO FLOW PARA O SEU ACERVO</p><h1>Seu episódio, take por take.</h1><p>Encontre a imagem certa, confira o vídeo e acompanhe cada versão. Tudo organizado no seu computador.</p><div class="actions"><button class="button primary" data-action="new-episode">+ Criar meu primeiro episódio</button><button class="button" data-action="demo">Conhecer com um piloto</button></div><p class="footnote">O piloto usa 3 takes e mídias sintéticas. Nenhum arquivo seu é necessário.</p>${!state.ffmpeg_available ? '<p class="notice">Instale FFmpeg para importar vídeos e gerar o piloto. Imagens podem ser organizadas agora.</p>' : ''}</section>`;
    return;
  }
  const ep = currentEpisode(), takes = takesForEpisode();
  const imageCount = takes.filter(t => activeBinding(t.id,'image')).length;
  const videoCount = takes.filter(t => activeBinding(t.id,'video')).length;
  const approvedCount = takes.filter(t => t.status === 'approved').length;
  const versionCount = takes.filter(t => ['image','video'].every(kind => {
    const binding = activeBinding(t.id,kind); return binding?.version;
  })).length;
  $('#app').innerHTML = `<section class="page-heading"><div><p class="eyebrow">ACERVO DE PRODUÇÃO</p><h1>${esc(ep.code)}${ep.title ? ` <span class="muted">/</span> ${esc(ep.title)}` : ''}</h1><p class="muted">Escolha um take. Confira as mídias. Decida o próximo passo.</p></div><button class="button primary" data-action="new-take">+ Novo take</button></section>
    ${ep.code === 'PILOTO' ? '<p class="notice">PILOTO · As imagens e o clipe são sintéticos. Use este episódio para testar o fluxo antes de importar o EP04.</p>' : ''}
    ${!state.ffmpeg_available ? '<p class="notice">FFmpeg ausente: importação de vídeos indisponível. Veja a instalação no README.</p>' : ''}
    <section class="summary" aria-label="Progresso do episódio">
      ${metric(imageCount,takes.length,'Imagens vinculadas','▧')}${metric(videoCount,takes.length,'Vídeos importados','▷')}${metric(versionCount,takes.length,'Pares com versões identificadas','⌗')}${metric(approvedCount,takes.length,'Takes aprovados pelo operador','✓')}
    </section>
    ${takes.length ? `<div class="workspace"><section><div class="section-head"><h2>Takes do episódio</h2><small>ORDEM DO ROTEIRO</small></div><div class="take-list">${takes.map(takeCard).join('')}</div></section>${detail()}</div>` : `<section class="empty-takes"><h2>Comece pelo primeiro take.</h2><p>Depois, vincule uma imagem-âncora e o vídeo gerado no Flow.</p><button class="button primary" data-action="new-take">+ Adicionar TAKE-01</button></section>`}`;
  dirty = false;
}

function metric(count,total,label,icon) {
  return `<div class="metric"><div class="metric-label"><span class="metric-icon" aria-hidden="true">${icon}</span><strong>${count}<span> / ${total}</span></strong></div><small>${label}</small></div>`;
}

function takeCard(take) {
  const image = activeBinding(take.id,'image'), video = activeBinding(take.id,'video');
  const preview = (binding, kind) => `<div class="tiny-preview">${binding ? `<img src="${assetById(binding.asset_id).thumbnail_url}" alt="${kind === 'image' ? 'Âncora' : 'Miniatura do vídeo'} do TAKE-${pad(take.number)}" loading="lazy">${kind === 'video' ? '<span class="play-label">▶ VÍDEO</span>' : ''}` : kind === 'image' ? '▧' : '▷'}</div>`;
  return `<button class="take-card ${take.id === takeId ? 'active' : ''}" data-action="take" data-id="${take.id}" aria-pressed="${take.id === takeId}"><div class="take-card-top"><span>TAKE-${pad(take.number)}</span><span class="status-dot ${take.status}" title="${statusLabels[take.status]}" aria-label="${statusLabels[take.status]}"></span></div><h3>${esc(take.title || 'Cena sem descrição')}</h3><div class="take-previews">${preview(image,'image')}${preview(video,'video')}</div><div class="take-card-foot"><span>Imagem: ${image ? 'sim' : 'não'}</span><span>Vídeo: ${video ? 'sim' : 'não'}</span></div></button>`;
}

function detail() {
  const take = currentTake();
  const image = activeBinding(take.id,'image'), video = activeBinding(take.id,'video');
  const versions = !!(image?.version && video?.version);
  const fact = (label, yes) => `<span class="fact ${yes ? 'yes' : ''}">${yes ? '✓' : '○'} ${label}: ${yes ? 'sim' : 'não'}</span>`;
  return `<section class="take-detail" aria-label="Take selecionado"><div class="detail-heading"><div><p class="eyebrow">TAKE SELECIONADO · ${esc(currentEpisode().code)}</p><h2>TAKE-${pad(take.number)}${take.title ? ` / ${esc(take.title)}` : ''}</h2></div><span class="status-chip ${take.status}"><span class="status-dot ${take.status}"></span>${statusLabels[take.status]}</span></div>
    <div class="facts">${fact('Imagem vinculada',!!image)}${fact('Vídeo importado',!!video)}${fact('Ambas as versões identificadas',versions)}</div>
    <div class="media-grid">${mediaPanel('image',image)}${mediaPanel('video',video)}</div>
    ${similarityWarnings(image)}
    <section class="decision"><h3>Decisão do operador</h3><p>Ter um arquivo não significa estar aprovado. A decisão se aplica ao par de mídias em uso.</p><div class="status-options">${Object.keys(statusLabels).map(status => `<button class="status-option ${take.status === status ? 'selected' : ''}" data-action="status" data-status="${status}" aria-pressed="${take.status === status}">${statusEmoji[status]} ${statusLabels[status]}</button>`).join('')}</div></section>
    <form id="take-form" class="editor"><div class="editor-top"><h3>Informações da cena</h3><span class="save-indicator" id="save-indicator">Informações salvas</span></div><div class="field-row"><label>Nº do take<input name="number" type="number" value="${take.number}" min="1" max="999" required></label><label>Descrição curta<input name="title" value="${esc(take.title)}" maxlength="200" placeholder="Ex.: Caramela manda limpar a cozinha"></label></div><label>Prompt correspondente <span class="muted">(opcional)</span><textarea name="prompt" maxlength="20000" placeholder="Cole o prompt utilizado no Flow…">${esc(take.prompt)}</textarea></label><label>Observações do operador<textarea name="notes" maxlength="20000" placeholder="Continuidade, correções, dúvidas sobre a versão…">${esc(take.notes)}</textarea></label><div class="editor-actions"><span class="field-help">A ordem dos cartões segue o número do take.</span><button class="button" type="submit">Salvar informações</button></div></form>
    <details class="comparison"><summary>Comparar âncoras e continuidade</summary><p>Imagens em uso no episódio, na ordem do roteiro. Clique para ampliar.</p><div class="comparison-grid">${takesForEpisode().map(t => {const binding=activeBinding(t.id,'image');return binding ? `<button class="compare-card" data-action="enlarge" data-id="${binding.asset_id}"><img src="${assetById(binding.asset_id).thumbnail_url}" alt="Âncora do TAKE-${pad(t.number)}" loading="lazy"><span>TAKE-${pad(t.number)} · ${esc(binding.version ? `V${binding.version}` : 'sem versão')}</span></button>` : '';}).join('') || '<p>Nenhuma âncora vinculada.</p>'}</div></details>
    </section>`;
}

function mediaPanel(kind, binding) {
  const asset = binding ? assetById(binding.asset_id) : null;
  const all = bindingsFor(takeId,kind).slice().reverse();
  const title = kind === 'image' ? 'Imagem-âncora' : 'Vídeo do Flow';
  return `<section class="media-panel"><div class="media-panel-head"><span>${kind === 'image' ? '▧' : '▷'} ${title}</span><span class="count">${all.length} ${all.length === 1 ? 'registro' : 'registros'}</span></div>
    ${asset ? kind === 'image' ? `<button class="media-stage enlarge" data-action="enlarge" data-id="${asset.id}" title="Ampliar imagem"><img src="${asset.url}" alt="${esc(friendly(binding))}"><span class="zoom-hint">↗ Ampliar</span></button>` : `<div class="media-stage"><video controls preload="metadata" poster="${asset.thumbnail_url}" src="${asset.url}" aria-label="${esc(friendly(binding))}">Seu navegador não reproduz este vídeo. Use o link para abrir a cópia.</video></div>` : `<div class="media-stage"><div class="media-empty"><span>${kind === 'image' ? '▧' : '▷'}</span><p>${kind === 'image' ? 'Vincule a imagem deste take' : 'Nenhum vídeo importado'}</p></div></div>`}
    ${asset ? `<p class="friendly-name">${esc(friendly(binding))}</p><p class="original-name" title="Nome original">Original: ${esc(binding.original_name || asset.original_name)}<br>${asset.width} × ${asset.height}${asset.duration ? ` · ${asset.duration.toFixed(1)} s` : ''}</p>` : '<p class="original-name">Importe uma cópia. O original será preservado.</p>'}
    <div class="media-actions"><button class="button small" data-action="upload" data-kind="${kind}">+ ${asset ? 'Nova versão' : 'Importar'}</button><button class="button small quiet" data-action="reuse" data-kind="${kind}">Vincular existente</button>${asset ? `<a href="${asset.url}/download" download>Abrir cópia ↗</a>` : ''}</div>
    ${kind === 'video' && asset ? '<p class="field-help">Se o navegador não reproduzir, abra a cópia no player local. MP4/H.264 oferece maior compatibilidade.</p>' : ''}
    ${all.length ? `<details class="version-list"><summary>Versões e vínculos (${all.length})</summary>${all.map(b => `<div class="version-row"><img src="${assetById(b.asset_id).thumbnail_url}" alt="Miniatura da versão" loading="lazy"><div><strong>${esc(b.version ? `V${b.version}` : 'Sem versão')} ${b.active ? '· Em uso' : ''}</strong><small>${esc(b.original_name || assetById(b.asset_id).original_name)}</small></div><div class="version-controls"><button class="button quiet" data-action="edit-binding" data-id="${b.id}">Identificar</button><button class="button quiet" data-action="select-binding" data-id="${b.id}" data-active="${b.active ? 'false' : 'true'}">${b.active ? 'Desvincular' : 'Usar'}</button></div></div>`).join('')}</details>` : ''}
    </section>`;
}

function assetLocation(assetId) {
  return state.bindings.filter(b => b.asset_id === assetId).map(b => {
    const take = state.takes.find(t => t.id === b.take_id);
    const ep = state.episodes.find(e => e.id === take.episode_id);
    return `${ep.code} TAKE-${pad(take.number)}${b.version ? ` V${b.version}` : ''}${b.active ? ' (em uso)' : ''}`;
  }).join(', ');
}

function similarityWarnings(image) {
  if (!image) return '';
  const identical = state.bindings.filter(b => b.asset_id === image.asset_id && b.id !== image.id);
  const similar = state.similarities.filter(pair => pair.left === image.asset_id || pair.right === image.asset_id);
  if (!identical.length && !similar.length) return '';
  return `<aside class="warning"><strong>⚠ Confira a semelhança das âncoras</strong><p>É apenas um aviso. Pode haver reutilização intencional; você decide.</p>${identical.length ? `<p><b>Arquivo idêntico (SHA-256)</b> também vinculado a: ${esc(assetLocation(image.asset_id))}.</p>` : ''}${similar.map(pair => {
    const other = assetById(pair.left === image.asset_id ? pair.right : pair.left);
    return `<div class="similar-pair"><button data-action="enlarge" data-id="${other.id}" aria-label="Ampliar imagem semelhante"><img src="${other.thumbnail_url}" alt="Imagem semelhante"></button><span><b>Visualmente parecida</b> · diferença perceptual ${pair.distance}/64<br>${esc(assetLocation(other.id) || other.original_name)}<br><button data-action="enlarge" data-id="${other.id}">Ver imagem para conferir</button></span></div>`;
  }).join('')}<p class="field-help">O aviso usa diferenças visuais aproximadas e pode errar. Não avalia continuidade nem qualidade.</p></aside>`;
}

function openDialog(title, fields, submit) {
  $('#dialog-title').textContent = title;
  $('#dialog-fields').innerHTML = fields;
  $('#dialog-error').textContent = '';
  dialogSubmit = submit;
  $('#form-dialog').showModal();
}

function newEpisode() {
  openDialog('Novo episódio', '<label>Código do episódio<input name="code" placeholder="EP04" maxlength="40" required></label><label>Nome <span class="muted">(opcional)</span><input name="title" placeholder="Ex.: A ordem na cozinha" maxlength="200"></label>', async form => {
    const result = await api('/api/episodes', {method:'POST', body:Object.fromEntries(form)});
    episodeId = result.id; takeId = null; await reload();
    toast('Episódio criado. Adicione o primeiro take.');
  });
}

function newTake() {
  const next = Math.max(0,...takesForEpisode().map(t => t.number)) + 1;
  openDialog('Novo take', `<label>Número na ordem do roteiro<input name="number" type="number" value="${next}" min="1" max="999" required></label><label>Descrição curta<input name="title" placeholder="Ex.: Caramela dá a ordem" maxlength="200"></label>`, async form => {
    const data = Object.fromEntries(form); data.number = Number(data.number);
    const result = await api(`/api/episodes/${episodeId}/takes`, {method:'POST', body:data});
    takeId = result.id; await reload(); toast('Take criado. Vincule a imagem-âncora.');
  });
}

function uploadDialog(kind) {
  const title = kind === 'image' ? 'Importar imagem-âncora' : 'Importar vídeo do Flow';
  const accept = kind === 'image' ? '.jpg,.jpeg,.png,.webp' : '.mp4,.mov,.m4v,.webm,.mkv,.avi';
  openDialog(title, `<p class="dialog-copy">Destino: <b>${esc(currentEpisode().code)} · TAKE-${pad(currentTake().number)}</b>. O aplicativo guarda uma cópia e mantém o nome original.</p><label>Arquivo<input name="file" type="file" accept="${accept}" required></label><label>Versão <span class="muted">(opcional)</span><input name="version" maxlength="40" placeholder="Ex.: 3 ou 1.3"><span class="field-help">Se você não souber, deixe em branco. A versão ficará não identificada.</span></label><label>Descrição desta mídia <span class="muted">(opcional)</span><input name="label" maxlength="200" placeholder="${esc(currentTake().title)}"></label><p class="field-help">A mídia nova ficará em uso. O take voltará a EM INVESTIGAÇÃO. Versões anteriores serão preservadas.</p>`, async form => {
    form.set('kind',kind);
    await api(`/api/takes/${takeId}/media`, {method:'POST', body:form});
    await reload(); toast('Cópia importada e vinculada. Confira o take antes de aprovar.');
  });
}

function reuseDialog(kind) {
  const assets = state.assets.filter(a => a.kind === kind);
  if (!assets.length) return toast('Importe uma mídia desse tipo primeiro. Depois você pode vinculá-la a outros takes.');
  openDialog('Vincular mídia existente', `<p class="dialog-copy">Escolha uma cópia já importada para <b>${esc(currentEpisode().code)} TAKE-${pad(currentTake().number)}</b>.</p><label>Arquivo<select name="asset_id">${assets.map(a => `<option value="${a.id}">${esc(a.original_name)} — ${esc(assetLocation(a.id))}</option>`).join('')}</select></label><div id="reuse-preview"></div><label>Versão <span class="muted">(opcional)</span><input name="version" maxlength="40" placeholder="Ex.: 3 ou 1.3"></label><label>Descrição desta mídia <span class="muted">(opcional)</span><input name="label" maxlength="200"></label><p class="field-help">O take voltará a EM INVESTIGAÇÃO. O vínculo anterior será preservado no histórico.</p>`, async form => {
    const data = Object.fromEntries(form); data.asset_id = Number(data.asset_id);
    await api(`/api/takes/${takeId}/link`, {method:'POST', body:data});
    await reload(); toast('Mídia vinculada. Confira a versão antes de aprovar.');
  });
  const select = $('#dialog-fields select');
  const preview = () => { $('#reuse-preview').innerHTML = `<div class="media-stage"><img src="${assetById(select.value).thumbnail_url}" alt="Prévia do arquivo selecionado"></div>`; };
  select.addEventListener('change',preview); preview();
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button || busy) return;
  const {action,id,kind,status,active} = button.dataset;
  run(async () => {
    switch (action) {
      case 'episode': episodeId=Number(id); takeId=null; renderAfterSelection(); break;
      case 'take': takeId=Number(id); render(); break;
      case 'new-episode': newEpisode(); break;
      case 'new-take': newTake(); break;
      case 'demo': {const result=await api('/api/demo',{method:'POST'}); episodeId=result.id; takeId=null; await reload(); toast('Piloto criado: 3 takes, 3 âncoras e 1 vídeo sintéticos.'); break;}
      case 'upload': uploadDialog(kind); break;
      case 'reuse': reuseDialog(kind); break;
      case 'enlarge': {const asset=assetById(id); $('#lightbox-image').src=asset.url; $('#lightbox-caption').textContent=assetLocation(asset.id) || asset.original_name; $('#lightbox').showModal(); break;}
      case 'status': await api(`/api/takes/${takeId}`,{method:'PATCH',body:{status}}); await reload(); toast(`Decisão salva: ${statusLabels[status]}.`); break;
      case 'select-binding': await api(`/api/bindings/${id}`,{method:'PATCH',body:{active:active==='true'}}); await reload(); toast(active==='true' ? 'Versão em uso alterada. Confira e decida novamente.' : 'Mídia desvinculada. A cópia e o histórico foram preservados.'); break;
      case 'edit-binding': {
        const binding=state.bindings.find(b => b.id===Number(id));
        openDialog('Identificar versão',`<p class="dialog-copy">Original: ${esc(binding.original_name || assetById(binding.asset_id).original_name)}</p><label>Versão<input name="version" value="${esc(binding.version)}" maxlength="40" placeholder="Ex.: 3 ou 1.3"></label><label>Descrição desta mídia<input name="label" value="${esc(binding.label)}" maxlength="200"></label><p class="field-help">Alterar a identificação devolve o take a EM INVESTIGAÇÃO.</p>`,async form => {await api(`/api/bindings/${id}`,{method:'PATCH',body:Object.fromEntries(form)}); await reload(); toast('Identificação salva.');});
        break;
      }
    }
  }, action==='demo' ? 'Criando piloto e miniaturas…' : 'Salvando…');
});

function renderAfterSelection() { takeId=takesForEpisode()[0]?.id ?? null; render(); }
$('#new-episode').addEventListener('click',() => run(async () => newEpisode()));
$('#restore').addEventListener('click',() => run(async () => { $('#restore-file').click(); }));
$('#restore-file').addEventListener('change',event => {
  const file=event.target.files[0]; if (!file) return;
  run(async () => {
    const form=new FormData(); form.set('file',file);
    const result=await api('/api/restore',{method:'POST',body:form});
    episodeId=result.episode_ids[0] ?? episodeId; takeId=null;
    await reload(); toast('Backup restaurado. Episódios existentes foram preservados.');
  },'Restaurando projeto e conferindo as mídias…').finally(() => {event.target.value='';});
});
$('#export').addEventListener('click',event => {
  event.preventDefault();
  run(async () => { window.location.assign('/api/export'); toast('Preparando ZIP com o registro e todas as cópias de mídia.'); },'Preparando exportação…');
});
document.addEventListener('input',event => {
  if (event.target.closest('#take-form')) {dirty=true; $('#save-indicator').textContent='Alterações pendentes';}
});
document.addEventListener('submit',event => {
  if (event.target.id==='take-form') {event.preventDefault(); run(async () => {render(); toast('Informações do take salvas.');});}
});
$('#dialog-form').addEventListener('submit',async event => {
  event.preventDefault(); if (busy || !dialogSubmit) return;
  const form=new FormData(event.target);
  // Keep the dialog and file selection open if the operation fails.
  await run(async () => {
    try {await dialogSubmit(form); $('#form-dialog').close();}
    catch(error) {$('#dialog-error').textContent=error.message; throw error;}
  }, form.has('file') ? 'Importando cópia e gerando miniatura…' : 'Salvando…');
});
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click',() => $('#form-dialog').close()));
$('#form-dialog').addEventListener('cancel',event => {if(busy)event.preventDefault();});
$('#close-lightbox').addEventListener('click',() => $('#lightbox').close());
window.addEventListener('beforeunload',event => {if(dirty || busy){event.preventDefault();event.returnValue='';}});
reload().catch(error => {$('#app').innerHTML='<p class="error">Não foi possível carregar o acervo. Confira o terminal e atualize a página.</p>';toast(error.message,true);});
