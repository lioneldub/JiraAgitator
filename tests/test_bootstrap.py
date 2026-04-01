import pytest
import json
import tempfile
import shutil
from pathlib import Path


def test_bootstrap_dry_run_creates_state():
    """Bootstrap en dry-run doit créer un state.json valide."""
    # Utiliser un répertoire temporaire
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Copier la config nécessaire
        src_config = Path(__file__).parent.parent / 'config'
        dst_config = tmppath / 'config'
        shutil.copytree(src_config, dst_config)

        # Importer bootstrap localement pour éviter les chemins globaux
        import sys
        src_root = Path(__file__).parent.parent
        sys.path.insert(0, str(src_root))

        # Changer de working directory temporaire
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmppath)
            from bootstrap_state import bootstrap
            bootstrap(['PROJ'], force_dry_run=True)

            # Vérifier le résultat
            state_file = tmppath / 'state.json'
            assert state_file.exists(), "state.json n'existe pas"

            state = json.loads(state_file.read_text())
            assert 'members' in state
            assert 'tickets' in state
            assert len(state['members']) > 0
            assert len(state['tickets']) > 0
        finally:
            os.chdir(original_cwd)
            sys.path.remove(str(src_root))
