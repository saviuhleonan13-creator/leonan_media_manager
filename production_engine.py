"""Conferência local de nomes: não abre mídias, banco ou arquivos de saída."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEOS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
NAME = re.compile(
    r"EP(?P<ep>[0-9]{1,3})[_ -]+(?P<kind>IMG|IMAGE|TAKE|T)[_ -]*"
    r"(?P<take>[0-9]+)(?P<tail>.*)", re.IGNORECASE
)
VERSION = re.compile(r"V[0-9]+(?:\.[0-9]+)?", re.IGNORECASE)
COPY_SUFFIX = re.compile(r"\s*\([0-9]+\)$")


def parse_filename(filename: str) -> dict | None:
    path = Path(filename)
    ext = path.suffix.lower()
    if ext not in IMAGES | VIDEOS:
        return None
    match = NAME.fullmatch(path.stem)
    if not match or not 1 <= int(match['take']) <= 999 or int(match['ep']) == 0:
        return None
    is_image = ext in IMAGES
    if match['kind'].upper() not in ({'IMG', 'IMAGE'} if is_image else {'TAKE', 'T'}):
        return None
    tail = match['tail']
    warnings = []
    if COPY_SUFFIX.search(tail):
        warnings.append('Sufixo de cópia/anexo: não identifica uma nova versão.')
        tail = COPY_SUFFIX.sub('', tail)
    version = None
    if tail:
        # Only a complete, delimited version is unambiguous. Never select one
        # version from multiple tokens or accept a numeric prefix of a take.
        if tail[0] in '_ -' and VERSION.fullmatch(tail.lstrip('_ -')):
            version = tail.lstrip('_ -').upper()
        else:
            warnings.append('Nome ou versão ambígua: conferir o sufixo completo.')
    return {
        'episode': f"EP{int(match['ep']):02d}", 'take': int(match['take']),
        'type': 'image' if is_image else 'video', 'filename': filename,
        'version': version, 'warnings': warnings,
    }


def is_link(metadata):
    # Windows junctions/reparse points are rejected too, including ancestors.
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, 'st_file_attributes', 0) & 0x400)


def selected_folder(source: Path) -> Path:
    folder = Path(os.path.abspath(source.expanduser()))
    for component in (*reversed(folder.parents), folder):
        if is_link(component.lstat()):
            raise ValueError('A pasta e seus caminhos pais não podem ser links ou junções.')
    if not stat.S_ISDIR(folder.lstat().st_mode):
        raise ValueError('O caminho selecionado não é uma pasta.')
    return folder


def preview(source: Path, episode: str, expected: int = 7) -> dict:
    match = re.fullmatch(r'EP([0-9]{1,3})', episode.upper())
    if not match or int(match[1]) == 0 or type(expected) is not int or not 1 <= expected <= 8:
        raise ValueError('Use --episode EP14 e --expected-takes entre 1 e 8.')
    code = f'EP{int(match[1]):02d}'
    try:
        folder = selected_folder(source)
        with os.scandir(folder) as entries:
            # lstat only: no media bytes read, no following symbolic links.
            files = [(entry.name, entry.stat(follow_symlinks=False)) for entry in entries]
    except FileNotFoundError as exc:
        raise ValueError('Pasta inexistente ou entrada removida durante a leitura; confira e tente novamente.') from exc
    except PermissionError as exc:
        raise ValueError('Acesso negado à pasta ou a uma entrada; confira as permissões.') from exc
    except OSError as exc:
        raise ValueError('Não foi possível ler a pasta; confira o caminho e tente novamente.') from exc
    takes = [dict(take=n, images=[], videos=[], warnings=[], review_needed=True)
             for n in range(1, expected + 1)]
    unmatched, other, excluded, ignored = [], [], [], []
    for name, metadata in sorted(files, key=lambda item: (item[0].casefold(), item[0])):
        if is_link(metadata):
            ignored.append({'filename': name, 'reason': 'Link ou junção ignorado; destino não consultado.'})
            continue
        if not stat.S_ISREG(metadata.st_mode):
            ignored.append({'filename': name, 'reason': 'Subpasta ou entrada não regular; não percorrida.'})
            continue
        path = Path(name)
        if path.suffix.lower() not in IMAGES | VIDEOS:
            ignored.append({'filename': name, 'reason': 'Extensão não reconhecida como mídia.'})
            continue
        reason = None
        if Path(path.stem).suffix.lower() in IMAGES | VIDEOS:
            reason = 'Extensões de mídia duplicadas; nome não usado como candidato.'
        parsed = parse_filename(name)
        if parsed is None:
            reason = reason or 'Nome incorreto ou não identificado; associação manual necessária.'
        if reason:
            unmatched.append(name)
            excluded.append({'filename': name, 'reason': reason})
            continue
        if parsed['episode'] != code:
            other.append(parsed)
            continue
        if parsed['take'] > expected:
            unmatched.append(name)
            excluded.append({'filename': name, 'reason': f"TAKE {parsed['take']:02d} fora do intervalo 01–{expected:02d}."})
            continue
        row = takes[parsed['take'] - 1]
        field = 'images' if parsed['type'] == 'image' else 'videos'
        row[field].append({k: parsed[k] for k in ('filename', 'version', 'warnings')})
    for row in takes:
        for field, label in (('images', 'imagem'), ('videos', 'vídeo')):
            if not row[field]:
                row['warnings'].append(f'Sem candidato de {label}; pode ser normal nesta etapa de produção.')
            if len(row[field]) > 1:
                row['warnings'].append(f'Múltiplos arquivos/possíveis versões de {label}: escolha humana necessária.')
            if any(item['version'] is None for item in row[field]):
                row['warnings'].append(f'Versão de {label} não identificada sem ambiguidade; não presumir V1.')
    return dict(mode='READ_ONLY_PREVIEW', episode=code, source=str(folder), takes=takes,
                unmatched_media=unmatched, excluded_media=excluded, other_episode_media=other,
                ignored_entries=ignored,
                note='Somente conferência de nomes. Versões no nome não são versões aprovadas. '
                     'Identidade, conteúdo, qualidade e continuidade não foram verificados. Nenhum arquivo foi alterado.')


def render_text(result: dict) -> str:
    lines = [f"CONFERÊNCIA — {result['episode']} — SOMENTE LEITURA", f"Pasta: {result['source']}", result['note']]
    for row in result['takes']:
        lines.append(f"\nTAKE {row['take']:02d}")
        for field, label in (('images', 'Imagem'), ('videos', 'Vídeo')):
            for item in row[field]:
                lines.append(f"  {label}: {item['filename']} | versão no nome: {item['version'] or 'não identificada'}")
                lines.extend(f'    Atenção: {warning}' for warning in item['warnings'])
        lines.extend(f'  Observação: {warning}' for warning in row['warnings'])
    for key, title in (('excluded_media', 'NOMES EXCLUÍDOS DA SELEÇÃO'),
                       ('other_episode_media', 'OUTROS EPISÓDIOS — SEM ASSOCIAÇÃO'),
                       ('ignored_entries', 'ENTRADAS IGNORADAS')):
        lines.append('\n' + title)
        for item in result[key]:
            detail = item.get('reason') or f"{item['episode']} / TAKE {item['take']:02d}"
            lines.append(f"  {item['filename']}: {detail}")
        if not result[key]:
            lines.append('  Nenhum.')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description='Conferir nomes de mídias sem importar nem aprovar.')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--episode', required=True)
    parser.add_argument('--expected-takes', type=int, default=7)
    parser.add_argument('--format', choices=('text', 'json'), default='text', help='Saída no terminal (padrão: text).')
    args = parser.parse_args()
    try:
        result = preview(args.source, args.episode, args.expected_takes)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == 'json' else render_text(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
