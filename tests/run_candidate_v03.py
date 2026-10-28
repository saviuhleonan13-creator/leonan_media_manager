"""Authorized V0.3 suite. Explicitly excludes restores into populated registries."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPECTED_INVENTORY_SHA256 = "d33754090ea6824977b965cfcc7623d25246252791522ec797a3a19540866974"
EXPECTED_COUNT = 84
EXCLUDED = {
    'test_deletion.DeletionTests.test_pre_deletion_backup_can_restore_removed_history',
    'test_app.MediaManagerTests.test_restore_merges_without_overwriting_existing_episode',
    'test_app.MediaManagerTests.test_restore_rejects_corruption_without_partial_registry',
    'test_app.MediaManagerTests.test_restore_rejects_traversal_and_bad_manifest',
}


def flatten(suite):
    for entry in suite:
        if isinstance(entry, unittest.TestSuite):
            yield from flatten(entry)
        else:
            yield entry


def main():
    discovered = list(flatten(unittest.defaultTestLoader.discover(str(ROOT / 'tests'))))
    ids = [test.id() for test in discovered]
    if len(ids) != len(set(ids)) or not EXCLUDED.issubset(ids):
        raise RuntimeError('Inventário inesperado: duplicação ou exclusão não encontrada.')
    digest = hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()
    if len(ids) != EXPECTED_COUNT or digest != EXPECTED_INVENTORY_SHA256:
        raise RuntimeError('Inventário diferente da revisão aprovada; nenhum teste executado.')
    selected = [test for test in discovered if test.id() not in EXCLUDED]
    print(f'Descobertos: {len(ids)}; duplicados: 0; excluídos: {len(EXCLUDED)}; selecionados: {len(selected)}', flush=True)
    for identifier in sorted(EXCLUDED):
        print(f'NÃO EXECUTADO (destino preenchido): {identifier}', flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    sys.exit(main())
