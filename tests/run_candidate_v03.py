"""Authorized V0.3 suite. Explicitly excludes restores into populated registries."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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
    selected = [test for test in discovered if test.id() not in EXCLUDED]
    print(f'Descobertos: {len(ids)}; duplicados: 0; excluídos: {len(EXCLUDED)}; selecionados: {len(selected)}', flush=True)
    for identifier in sorted(EXCLUDED):
        print(f'NÃO EXECUTADO (destino preenchido): {identifier}', flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    sys.exit(main())
