from pathlib import Path

import pytest

from scripts.check_image import check_no_credentials


@pytest.mark.parametrize("name", ["gha-creds-test.json", "nested/gha-creds-test.json", ".env", "scripts/credentials.json"])
def test_image_rejects_credentials(tmp_path, name):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("test placeholder")
    with pytest.raises(AssertionError):
        check_no_credentials(tmp_path)


def test_clean_image_and_build_configuration(tmp_path):
    check_no_credentials(tmp_path)
    root = Path(__file__).resolve().parents[1]
    for name in (".gitignore", ".dockerignore", ".gcloudignore"):
        assert "gha-creds-*.json" in (root / name).read_text().splitlines()
    workflow = (root / ".github/workflows/deploy.yaml").read_text()
    assert workflow.index("scripts.check_image") < workflow.index("google-github-actions/auth@")
